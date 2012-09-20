# Copyright 2012 Anton Beloglazov
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" The main data collector module.

The data collector is deployed on every compute host and is executed
periodically to collect the CPU utilization data for each VM running
on the host and stores the data in the local file-based data store.
The data is stored as the average number of MHz consumed by a VM
during the last measurement interval. The CPU usage data are stored as
integers. This data format is portable: the stored values can be
converted to the CPU utilization for any host or VM type, supporting
heterogeneous hosts and VMs.

The actual data is obtained from Libvirt in the form of the CPU time
consumed by a VM to date. Using the CPU time collected at the previous
time frame, the CPU time for the past time interval is calculated.
According to the CPU frequency of the host and the length of the time
interval, the CPU time is converted into the required average MHz
consumed by the VM over the last time interval. The collected data are
stored both locally and submitted to the central database. The number
of the latest data values stored locally and passed to the underload /
overload detection and VM selection algorithms is defined using the
`data_collector_data_length` option in the configuration file.

At the beginning of every execution, the data collector obtains the
set of VMs currently running on the host using the Nova API and
compares them to the VMs running on the host at the previous time
step. If new VMs have been found, the data collector fetches the
historical data about them from the central database and stores the
data in the local file-based data store. If some VMs have been
removed, the data collector removes the data about these VMs from the
local data store.

The data collector stores the resource usage information locally in
files in the <local_data_directory>/vm directory, where
<local_data_directory> is defined in the configuration file using
the local_data_directory option. The data for each VM are stored in
a separate file named according to the UUID of the corresponding VM.
The format of the files is a new line separated list of integers
representing the average CPU consumption by the VMs in MHz during the
last measurement interval.

The data collector will be implemented as a Linux daemon running in
the background and collecting data on the resource usage by VMs every
data_collector_interval seconds. When the data collection phase is
invoked, the component performs the following steps:

1. Read the names of the files from the <local_data_directory>/vm
   directory to determine the list of VMs running on the host at the
   last data collection.

2. Call the Nova API to obtain the list of VMs that are currently
   active on the host.

3. Compare the old and new lists of VMs and determine the newly added
   or removed VMs.

4. Delete the files from the <local_data_directory>/vm directory
   corresponding to the VMs that have been removed from the host.

5. Fetch the latest data_collector_data_length data values from the
   central database for each newly added VM using the database
   connection information specified in the sql_connection option and
   save the data in the <local_data_directory>/vm directory.

6. Call the Libvirt API to obtain the CPU time for each VM active on
   the host.

7. Transform the data obtained from the Libvirt API into the average
   MHz according to the frequency of the host's CPU and time interval
   from the previous data collection.

8. Store the converted data in the <local_data_directory>/vm
   directory in separate files for each VM, and submit the data to the
   central database.

9. Schedule the next execution after data_collector_interval
   seconds.
"""

from contracts import contract
from neat.contracts_extra import *

import time
from collections import deque

import neat.common as common
from neat.config import *
from neat.db_utils import *


@contract
def start():
    """ Start the data collector loop.

    :return: The final state.
     :rtype: dict(str: *)
    """
    config = read_and_validate_config([DEFAILT_CONFIG_PATH, CONFIG_PATH], REQUIRED_FIELDS)
    return common.start(
        init_state,
        execute,
        config,
        int(config.get('data_collector_interval')))


@contract
def init_state(config):
    """ Initialize a dict for storing the state of the data collector.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :return: A dictionary containing the initial state of the data collector.
     :rtype: dict
    """
    vir_connection = libvirt.openReadOnly(None)
    if vir_connection is None:
        print 'Failed to open connection to the hypervisor'
        sys.exit(1)
    return {'previous_time': 0,
            'previous_cpu_time': dict(),
            'vir_connect': vir_connection,
            'physical_cpus': common.physical_cpu_count(vir_connection),
            'db': init_db(config.get('sql_connection'))}


def execute(config, state):
    """ Execute a data collection iteration.

1. Read the names of the files from the <local_data_directory>/vm
   directory to determine the list of VMs running on the host at the
   last data collection.

2. Call the Nova API to obtain the list of VMs that are currently
   active on the host.

3. Compare the old and new lists of VMs and determine the newly added
   or removed VMs.

4. Delete the files from the <local_data_directory>/vm directory
   corresponding to the VMs that have been removed from the host.

5. Fetch the latest data_collector_data_length data values from the
   central database for each newly added VM using the database
   connection information specified in the sql_connection option and
   save the data in the <local_data_directory>/vm directory.

6. Call the Libvirt API to obtain the CPU time for each VM active on
   the host. Transform the data obtained from the Libvirt API into the
   average MHz according to the frequency of the host's CPU and time
   interval from the previous data collection.

8. Store the converted data in the <local_data_directory>/vm
   directory in separate files for each VM, and submit the data to the
   central database.

    :param config: A config dictionary.
     :type config: dict(str: *)

    :param state: A state dictionary.
     :type state: dict(str: *)

    :return: The updated state dictionary.
     :rtype: dict(str: *)
    """
    path = common.build_local_vm_path(config.get('local_data_directory'))
    vms_previous = get_previous_vms(path)
    vms_current = get_current_vms()
    vms_added = get_added_vms(vms_previous, vms_current)
    vms_removed = get_removed_vms(vms_previous, vms_current)
    cleanup_local_data(vms_removed)
    data_length = int(config.get('data_collector_data_length'))
    added_vm_data = fetch_remote_data(config.get('db'),
                                      data_length,
                                      vms_added)
    write_data_locally(path, added_vm_data, data_length)
    current_time = time.time()
    (cpu_time, cpu_mhz) = get_cpu_mhz(state['vir_connection'],
                                      state['physical_cpus'],
                                      state['previous_cpu_time'],
                                      state['previous_time'],
                                      current_time,
                                      vms_current,
                                      added_vm_data)
    state['previous_time'] = current_time
    state['previous_cpu_time'] = cpu_time
    append_data_locally(path, cpu_mhz, data_length)
    append_data_remotely(config.get('db'), cpu_mhz)
    return state


@contract
def get_previous_vms(path):
    """ Get a list of VM UUIDs from the path.

    :param path: A path to read VM UUIDs from.
     :type path: str

    :return: The list of VM UUIDs from the path.
     :rtype: list(str)
    """
    return os.listdir(path)


@contract()
def get_current_vms(vir_connection):
    """ Get a list of VM UUIDs from libvirt.

    :param vir_connection: A libvirt connection object.
     :type vir_connection: virConnect

    :return: The list of VM UUIDs from libvirt.
     :rtype: list(str)
    """
    vm_uuids = []
    for vm_id in vir_connection.listDomainsID():
        vm_uuids.append(vir_connection.lookupByID(vm_id).UUIDString())
    return vm_uuids


@contract
def get_added_vms(previous_vms, current_vms):
    """ Get a list of newly added VM UUIDs.

    :param previous_vms: A list of VMs at the previous time frame.
     :type previous_vms: list(str)

    :param current_vms: A list of VM at the current time frame.
     :type current_vms: list(str)

    :return: A list of VM UUIDs that have been added since the last time frame.
     :rtype: list(str)
    """
    return substract_lists(current_vms, previous_vms)


@contract
def get_removed_vms(previous_vms, current_vms):
    """ Get a list of VM UUIDs removed since the last time frame.

    :param previous_vms: A list of VMs at the previous time frame.
     :type previous_vms: list(str)

    :param current_vms: A list of VM at the current time frame.
     :type current_vms: list(str)

    :return: A list of VM UUIDs that have been removed since the last time frame.
     :rtype: list(str)
    """
    return substract_lists(previous_vms, current_vms)


@contract
def substract_lists(list1, list2):
    """ Return the elements of list1 that are not in list2.

    :param list1: The first list.
     :type list1: list

    :param list2: The second list.
     :type list2: list

    :return: The list of element of list 1 that are not in list2.
     :rtype: list
    """
    return list(set(list1).difference(list2))


@contract
def cleanup_local_data(path, vms):
    """ Delete the local data related to the removed VMs.

    :param path: A path to removed VM data from.
     :type path: str

    :param vms: A list of removed VM UUIDs.
     :type vms: list(str)
    """
    for vm in vms:
        os.remove(os.path.join(path, vm))


@contract
def fetch_remote_data(db, data_length, uuids):
    """ Fetch VM data from the central DB.

    :param db: The database object.
     :type db: Database

    :param data_length: The length of data to fetch.
     :type data_length: int

    :param uuids: A list of VM UUIDs to fetch data for.
     :type uuids: list(str)

    :return: A dictionary of VM UUIDs and the corresponding data.
     :rtype: dict(str : list(int))
    """
    result = dict()
    for uuid in uuids:
        result[uuid] = db.select_cpu_mhz_for_vm(uuid, data_length)
    return result


@contract
def write_data_locally(path, data, data_length):
    """ Write a set of CPU MHz values for a set of VMs.

    :param path: A path to write the data to.
     :type path: str

    :param data: A map of VM UUIDs onto the corresponing CPU MHz history.
     :type data: dict(str : list(int))

    :param data_length: The maximum allowed length of the data.
     :type data_length: int
    """
    for uuid, values in data.items():
        with open(os.path.join(path, uuid), 'w') as f:
            if data_length > 0:
                f.write('\n'.join([str(x) for x in values[-data_length:]]) + '\n')


@contract
def append_data_locally(path, data, data_length):
    """ Write a CPU MHz value for each out of a set of VMs.

    :param path: A path to write the data to.
     :type path: str

    :param data: A map of VM UUIDs onto the corresponing CPU MHz values.
     :type data: dict(str : int)

    :param data_length: The maximum allowed length of the data.
     :type data_length: int
    """
    for uuid, value in data.items():
        with open(os.path.join(path, uuid), 'r+') as f:
            values = deque(f.read().strip().splitlines(), data_length)
            values.append(value)
            f.truncate(0)
            f.seek(0)
            f.write('\n'.join([str(x) for x in values]) + '\n')


@contract
def append_data_remotely(db, data):
    """ Submit a CPU MHz values to the central database.

    :param db: The database object.
     :type db: Database

    :param data: A map of VM UUIDs onto the corresponing CPU MHz values.
     :type data: dict(str : int)
    """
    db.insert_cpu_mhz(data)


@contract
def get_cpu_mhz(vir_connection, physical_cpus, previous_cpu_time,
                previous_time, current_time, current_vms, added_vm_data):
    """ Get the average CPU utilization in MHz for a set of VMs.

    :param vir_connection: A libvirt connection object.
     :type vir_connection: virConnect

    :param physical_cpus: The number of physical CPUs.
     :type physical_cpus: int

    :param previous_cpu_time: A dictionary of previous CPU times for the VMs.
     :type previous_cpu_time: dict(str : int)

    :param previous_time: The previous timestamp.
     :type previous_time: int

    :param current_time: The previous timestamp.
     :type current_time: int

    :param current_vms: A list of VM UUIDs.
     :type current_vms: list(str)

    :param added_vm_data: A dictionary of VM UUIDs and the corresponding data.
     :type added_vm_data: dict(str : list(int))

    :return: The updated CPU times and average CPU utilization in MHz.
     :rtype: tuple(dict(str : int), dict(str : int))
    """
    previous_vms = previous_cpu_time.keys()
    added_vms = get_added_vms(previous_vms, current_vms)
    removed_vms = get_removed_vms(previous_vms, current_vms)
    cpu_mhz = {}

    for uuid, cpu_time in previous_cpu_time.items():
        current_cpu_time = get_cpu_time(vir_connection, uuid)
        cpu_mhz[uuid] = calculate_cpu_mhz(physical_cpus, previous_time,
                                          current_time, cpu_time,
                                          current_cpu_time)
        previous_cpu_time[uuid] = current_cpu_time

    for uuid in added_vms:
        if added_vm_data[uuid]:
            cpu_mhz[uuid] = added_vm_data[uuid][-1]
        previous_cpu_time[uuid] = get_cpu_time(vir_connection, uuid)

    for uuid in removed_vms:
        del previous_cpu_time[uuid]
        del cpu_mhz[uuid]

    return previous_cpu_time, cpu_mhz


@contract
def get_cpu_time(vir_connection, uuid):
    """ Get the CPU time of a VM specified by the UUID using libvirt.

    :param vir_connection: A libvirt connection object.
     :type vir_connection: virConnect

    :param uuid: The UUID of a VM.
     :type uuid: str[36]

    :return: The CPU time of the VM.
     :rtype: int
    """
    domain = vir_connection.lookupByUUIDString(uuid)
    return domain.getCPUStats(True, 0)[0]['cpu_time']


@contract
def calculate_cpu_mhz(cpus, previous_time, current_time,
                      previous_cpu_time, current_cpu_time):
    """ Calculate the average CPU utilization in MHz for a period of time.

    :param cpus: The number of physical CPUs.
     :type cpus: int

    :param previous_time: The previous timestamp.
     :type previous_time: int

    :param current_time: The current timestamp.
     :type current_time: int

    :param previous_cpu_time: The previous CPU time of the domain.
     :type previous_cpu_time: int

    :param current_cpu_time: The current CPU time of the domain.
     :type current_cpu_time: int

    :return: The average CPU utilization in MHz.
     :rtype: int
    """
    return int((current_cpu_time - previous_cpu_time) /
               ((current_time - previous_time) * 1000000000 * cpus))