#!/usr/bin/env python3
# Copyright 2017 Eayun, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import sys

from oslo_config import cfg  # noqa

from neutron.agent.l3 import ha
from neutron.common import config
from neutron.common import eventlet_utils
from neutron.tests.common.agents import l3_agent


eventlet_utils.monkey_patch()


# NOTE(ralonsoh): remove when eventlet is removed.
def patch_keepalived_notifications_server():
    def start_keepalived_notifications_server():
        pass

    ha.AgentMixin._start_keepalived_notifications_server = (
        start_keepalived_notifications_server)


if __name__ == "__main__":
    config.register_common_config_options()
    patch_keepalived_notifications_server()
    sys.exit(l3_agent.main())
