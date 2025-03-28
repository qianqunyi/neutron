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

from neutron_lib.api.definitions import agent as agent_apidef
from neutron_lib.api.definitions import availability_zone as az_def
from neutron_lib.api.definitions import availability_zone_filter as azf_def
from neutron_lib import context
from neutron_lib.exceptions import availability_zone as az_exc
from oslo_config import cfg

from neutron.db import agents_db
from neutron.db import db_base_plugin_v2
from neutron.extensions import agent
from neutron.extensions import availability_zone as az_ext
from neutron.tests.common import helpers
from neutron.tests.common import test_db_base_plugin_v2


class AZExtensionManager:

    def get_resources(self):
        agent.Agent().update_attributes_map(az_def.RESOURCE_ATTRIBUTE_MAP)
        return (az_ext.Availability_zone.get_resources() +
                agent.Agent.get_resources())

    def get_actions(self):
        return []

    def get_request_extensions(self):
        return []


class AZTestPlugin(db_base_plugin_v2.NeutronDbPluginV2,
                   agents_db.AgentDbMixin):
    supported_extension_aliases = [agent_apidef.ALIAS, az_def.ALIAS,
                                   azf_def.ALIAS]


class AZTestCommon(test_db_base_plugin_v2.NeutronDbPluginV2TestCase):
    def _register_azs(self):
        self.agent1 = helpers.register_dhcp_agent(host='host1', az='nova1')
        self.agent2 = helpers.register_dhcp_agent(host='host2', az='nova2')
        self.agent3 = helpers.register_l3_agent(host='host2', az='nova2')
        self.agent4 = helpers.register_l3_agent(host='host3', az='nova3')
        self.agent5 = helpers.register_l3_agent(host='host4', az='nova2')


class TestAZAgentCase(AZTestCommon):
    def setUp(self):
        plugin = ('neutron.tests.unit.extensions.'
                  'test_availability_zone.AZTestPlugin')
        ext_mgr = AZExtensionManager()
        super().setUp(plugin=plugin, ext_mgr=ext_mgr)

    def test_list_availability_zones(self):
        self._register_azs()
        helpers.set_agent_admin_state(self.agent3['id'], admin_state_up=False)
        helpers.set_agent_admin_state(self.agent4['id'], admin_state_up=False)
        expected = [
            {'name': 'nova1', 'resource': 'network', 'state': 'available'},
            {'name': 'nova2', 'resource': 'network', 'state': 'available'},
            {'name': 'nova2', 'resource': 'router', 'state': 'available'},
            {'name': 'nova3', 'resource': 'router', 'state': 'unavailable'}]
        res = self._list('availability_zones', as_admin=True)
        azs = res['availability_zones']
        self.assertCountEqual(expected, azs)
        # not admin case
        res = self._list('availability_zones', as_admin=False)
        azs = res['availability_zones']
        self.assertCountEqual(expected, azs)

    def test_list_availability_zones_with_filter(self):
        self._register_azs()
        helpers.set_agent_admin_state(self.agent3['id'], admin_state_up=False)
        helpers.set_agent_admin_state(self.agent4['id'], admin_state_up=False)
        expected = [
            {'name': 'nova1', 'resource': 'network', 'state': 'available'},
            {'name': 'nova2', 'resource': 'network', 'state': 'available'},
            {'name': 'nova2', 'resource': 'router', 'state': 'available'},
            {'name': 'nova3', 'resource': 'router', 'state': 'unavailable'}]
        res = self._list('availability_zones', as_admin=True)
        azs = res['availability_zones']
        self.assertCountEqual(expected, azs)
        # list with filter of 'name'
        res = self._list('availability_zones',
                         query_params="name=nova1",
                         as_admin=True)
        azs = res['availability_zones']
        self.assertCountEqual(expected[:1], azs)
        # list with filter of 'resource'
        res = self._list('availability_zones',
                         query_params="resource=router",
                         as_admin=True)
        azs = res['availability_zones']
        self.assertCountEqual(expected[-2:], azs)
        # list with filter of 'state' as 'available'
        res = self._list('availability_zones',
                         query_params="state=available",
                         as_admin=True)
        azs = res['availability_zones']
        self.assertCountEqual(expected[:3], azs)
        # list with filter of 'state' as 'unavailable'
        res = self._list('availability_zones',
                         query_params="state=unavailable",
                         as_admin=True)
        azs = res['availability_zones']
        self.assertCountEqual(expected[-1:], azs)

    def test_list_agent_with_az(self):
        helpers.register_dhcp_agent(host='host1', az='nova1')
        res = self._list('agents', as_admin=True)
        self.assertEqual('nova1',
                         res['agents'][0]['availability_zone'])

    def test_validate_availability_zones(self):
        self._register_azs()
        ctx = context.Context('', 'tenant_id')
        self.plugin.validate_availability_zones(ctx, 'network',
                                                ['nova1', 'nova2'])
        self.plugin.validate_availability_zones(ctx, 'router',
                                                ['nova2', 'nova3'])
        self.assertRaises(az_exc.AvailabilityZoneNotFound,
                          self.plugin.validate_availability_zones,
                          ctx, 'router', ['nova1'])


class TestAZNetworkCase(AZTestCommon):
    def setUp(self):
        ext_mgr = AZExtensionManager()
        super().setUp(plugin='ml2', ext_mgr=ext_mgr)

    def test_availability_zones_in_create_response(self):
        with self.network() as net:
            self.assertIn('availability_zone_hints', net['network'])
            self.assertIn('availability_zones', net['network'])

    def test_create_network_with_az(self):
        self._register_azs()
        az_hints = ['nova1']
        with self.network(availability_zone_hints=az_hints) as net:
            res = self._show('networks', net['network']['id'])
            self.assertCountEqual(az_hints,
                                  res['network']['availability_zone_hints'])

    def test_create_network_with_azs(self):
        self._register_azs()
        az_hints = ['nova1', 'nova2']
        with self.network(availability_zone_hints=az_hints) as net:
            res = self._show('networks', net['network']['id'])
            self.assertCountEqual(az_hints,
                                  res['network']['availability_zone_hints'])

    def test_create_network_without_az(self):
        with self.network() as net:
            res = self._show('networks', net['network']['id'])
            self.assertEqual([], res['network']['availability_zone_hints'])

    def test_create_network_with_empty_az(self):
        with self.network(availability_zone_hints=[]) as net:
            res = self._show('networks', net['network']['id'])
            self.assertEqual([], res['network']['availability_zone_hints'])

    def test_create_network_with_not_exist_az(self):
        res = self._create_network(self.fmt, 'net', True,
                                   availability_zone_hints=['nova3'])
        self.assertEqual(404, res.status_int)

    def test_create_network_with_default_azs_not_existing(self):
        self._register_azs()
        cfg.CONF.set_default('default_availability_zones', ['nova4'])
        res = self._create_network(self.fmt, 'net', True)
        self.assertEqual(404, res.status_int)

    def test_create_network_with_default_azs_existing_az(self):
        self._register_azs()
        az_hints = ['nova1', 'nova2']
        cfg.CONF.set_default('default_availability_zones', az_hints)
        with self.network() as net:
            res = self._show('networks', net['network']['id'])
            self.assertCountEqual(az_hints,
                                  res['network']['availability_zone_hints'])
