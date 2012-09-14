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

""" Functions for defing the NLP problem of the MHOD algorithm.
"""

from contracts import contract
from neat.contracts_extra import *

import operator


@contract
def build_objective(ls, state_vector, p):
    """ Creates an objective function, which is a sum of the L functions.

    :param ls: A list of L functions.
     :type ls: list(function)

    :param state-vector: A state vector.
     :type state-vector: list(int)

    :param p: A matrix of transition probabilities.
     :type p: list(list(number))

    :return: An objective function.
     :rtype: function
    """
    def objective(*m):
        return sum(l(state_vector, p, m) for l in ls)
    return objective


@contract
def build_constraint(otf, migration_time, ls, state_vector, p, time_in_states, time_in_state_n):
    """ Creates a constraint for the optimization problem from the L functions.

    :param otf: The OTF parameter.
     :type otf: float

    :param migration_time: The VM migration time in seconds.
     :type migration_time: int

    :param ls: A list of L functions.
     :type ls: list(function)

    :param state-vector: A state vector.
     :type state-vector: list(int)

    :param p: A matrix of transition probabilities.
     :type p: list(list(number))

    :param time_in_states: The total time on all the states in seconds.
     :type time_in_states: int

    :param time_in_state_n: The total time in the state N in seconds.
     :type time_in_state_n: int

    :return: The created constraint.
     :rtype: tuple(function, function, number)
    """
    def constraint(*m):
        return float(migration_time + time_in_state_n + ls[-1](state_vector, p, m)) / \
               (migration_time + time_in_states + sum(l(state_vector, p, m) for l in ls))
    return (constraint, operator.le, otf)