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

from mocktest import *
from pyqcy import *

import neat.common as common


class Common(TestCase):

    @qc(10)
    def start(iterations=int_(0, 10)):
        with MockTransaction:
            config = {'option': 'value'}
            state = {'property': 'value'}
            fn = mock('function container')
            expect(fn).init_state(any_dict).and_return(state).once()
            expect(fn).execute(any_dict, any_dict). \
                and_return(state).exactly(iterations).times()
            assert common.start(fn.init_state,
                                fn.execute,
                                config,
                                0,
                                iterations) == state

    def test_frange(self):
        self.assertEqual([round(x, 1) for x in common.frange(0, 1.0, 0.5)],
                         [0.0, 0.5, 1.0])
        self.assertEqual([round(x, 1) for x in common.frange(0, 1.0, 0.2)],
                         [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
