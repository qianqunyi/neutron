# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
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

import testresources
import testscenarios
import testtools

from neutron_lib.db import api as db_api
from neutron_lib import fixture as lib_fixtures
from oslo_config import cfg
from oslo_db import exception as oslodb_exception
from oslo_db.sqlalchemy import provision

from neutron.api import wsgi
from neutron.db.migration import cli as migration
# Import all data models
from neutron.db.migration.models import head  # noqa
from neutron.tests import base


class ExpectedException(testtools.ExpectedException):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if super().__exit__(exc_type,
                            exc_value,
                            traceback):
            self.exception = exc_value
            return True
        return False


def create_request(path, body, content_type, method='GET',
                   query_string=None, context=None, headers=None):
    headers = headers or {}
    if query_string:
        url = f"{path}?{query_string}"
    else:
        url = path
    req = wsgi.Request.blank(url)
    req.method = method
    req.headers = {}
    req.headers['Accept'] = content_type
    req.headers.update(headers)
    if isinstance(body, str):
        req.body = body.encode()
    else:
        req.body = body
    if context:
        req.environ['neutron.context'] = context
    return req


class StaticSqlFixtureNoSchema(lib_fixtures.SqlFixture):
    """Fixture which keeps a single sqlite memory database at the global
    scope

    """

    _GLOBAL_RESOURCES = False

    @classmethod
    def _init_resources(cls):
        if cls._GLOBAL_RESOURCES:
            return
        cls._GLOBAL_RESOURCES = True
        cls.database_resource = provision.DatabaseResource(
            "sqlite", db_api.get_context_manager())
        dependency_resources = {}
        for name, resource in cls.database_resource.resources:
            dependency_resources[name] = resource.getResource()
        cls.engine = dependency_resources['backend'].engine

    def _delete_from_schema(self, engine):
        pass


class OpportunisticSqlFixture(lib_fixtures.SqlFixture):
    """Fixture which uses testresources with oslo_db provisioning to
    check for available backends and optimize test runs.

    Requires that the test itself implement the resources attribute.

    """

    DRIVER = 'sqlite'

    def __init__(self, test):
        super().__init__()
        self.test = test

    @classmethod
    def _generate_schema_w_migrations(cls, engine):
        alembic_configs = migration.get_alembic_configs()
        with engine.connect() as conn:
            for alembic_config in alembic_configs:
                alembic_config.attributes['connection'] = conn
                alembic_config.neutron_config = cfg.CONF
                alembic_config.neutron_config.set_override(
                    'connection', str(engine.url), group='database')
                migration.do_alembic_command(
                    alembic_config, 'upgrade', 'heads')

    def _delete_from_schema(self, engine):
        if self.test.BUILD_SCHEMA:
            super()._delete_from_schema(engine)

    def _init_resources(self):
        testresources.setUpResources(
            self.test, self.test.resources, testresources._get_result())
        self.addCleanup(self._cleanup_resources)

        # unfortunately, fixtures won't let us call a skip() from
        # here.  So the test has to check this also.
        # see https://github.com/testing-cabal/fixtures/issues/31
        if hasattr(self.test, 'db'):
            self.engine = self.test.engine = self.test.db.engine

    def _cleanup_resources(self):
        testresources.tearDownResources(
            self.test, self.test.resources, testresources._get_result())

        if self.test.CLEAN_DB_AFTER_TEST:
            self.test._database_resources.pop(self.test.DRIVER)
            self.test._schema_resources.pop((self.test.DRIVER, None))

    @classmethod
    def resources_collection(cls, test):
        # reimplement current oslo.db code.
        # FIXME(zzzeek) The patterns here are up in the air enough
        # that I think keeping this totally separate will give us the
        # most leverage in being able to fix oslo.db in an upcoming
        # release, then port neutron back to the working version.

        driver = test.DRIVER

        if driver not in test._database_resources:
            try:
                test._database_resources[driver] = \
                    provision.DatabaseResource(driver)
            except oslodb_exception.BackendNotAvailable:
                test._database_resources[driver] = None

        database_resource = test._database_resources[driver]
        if database_resource is None:
            return []

        key = (driver, None)
        if test.BUILD_SCHEMA:
            if key not in test._schema_resources:
                test._schema_resources[key] = provision.SchemaResource(
                    database_resource,
                    cls._generate_schema_w_migrations
                    if test.BUILD_WITH_MIGRATIONS
                    else cls._generate_schema, teardown=False)

            schema_resource = test._schema_resources[key]
            return [
                ('schema', schema_resource),
                ('db', database_resource)
            ]
        return [('db', database_resource)]


class BaseSqlTestCase:
    BUILD_SCHEMA = True

    def setUp(self):
        super().setUp()

        self._setup_database_fixtures()

    def _setup_database_fixtures(self):
        if self.BUILD_SCHEMA:
            fixture = lib_fixtures.StaticSqlFixture()
        else:
            fixture = StaticSqlFixtureNoSchema()
        self.useFixture(fixture)
        self.engine = fixture.engine


class SqlTestCaseLight(BaseSqlTestCase, base.DietTestCase):
    """All SQL taste, zero plugin/rpc sugar"""


class SqlTestCase(BaseSqlTestCase, base.BaseTestCase):
    """regular sql test"""


class OpportunisticDBTestMixin:
    """Mixin that converts a BaseSqlTestCase to use the
    OpportunisticSqlFixture.
    """

    SKIP_ON_UNAVAILABLE_DB = not base.bool_from_env('OS_FAIL_ON_MISSING_DEPS')

    FIXTURE = OpportunisticSqlFixture

    BUILD_WITH_MIGRATIONS = False
    CLEAN_DB_AFTER_TEST = False

    def _setup_database_fixtures(self):
        self.useFixture(self.FIXTURE(self))

        if not hasattr(self, 'db'):
            msg = "backend '%s' unavailable" % self.DRIVER
            if self.SKIP_ON_UNAVAILABLE_DB:
                self.skipTest(msg)
            self.fail(msg)

    _schema_resources = {}
    _database_resources = {}

    @property
    def resources(self):
        """this attribute is used by testresources for optimized
        sorting of tests.

        This is the big requirement that allows testresources to sort
        tests such that database "resources" can be kept open for
        many tests at once.

        IMO(zzzeek) "sorting" should not be needed; only that necessary
        resources stay open as long as they are needed (or long enough to
        reduce overhead).  testresources would be improved to not depend on
        custom, incompatible-with-pytest "suite classes", fixture information
        leaking out of the Fixture classes themselves, and exotic sorting
        schemes for something that can nearly always be handled "good enough"
        with unittest-standard setupclass/setupmodule schemes.

        """

        return self.FIXTURE.resources_collection(self)


class MySQLTestCaseMixin(OpportunisticDBTestMixin):
    """Mixin that turns any BaseSqlTestCase into a MySQL test suite.

    If the MySQL db is unavailable then this test is skipped, unless
    OS_FAIL_ON_MISSING_DEPS is enabled.
    """
    DRIVER = "mysql"


def module_load_tests(loader, found_tests, pattern):
    """Apply OptimisingTestSuite on a per-module basis.

    FIXME(zzzeek): oslo.db provides this but the contract that
    "pattern" should be None no longer seems to behave as it used
    to at the module level, so this function needs to be added in this
    form.

    """

    result = testresources.OptimisingTestSuite()
    found_tests = testscenarios.load_tests_apply_scenarios(
        loader, found_tests, pattern)
    result.addTest(found_tests)
    return result


class WebTestCase(SqlTestCase):
    fmt = 'json'

    def setUp(self):
        super().setUp()
        json_deserializer = wsgi.JSONDeserializer()
        self._deserializers = {
            'application/json': json_deserializer,
        }

    def deserialize(self, response):
        ctype = 'application/%s' % self.fmt
        data = self._deserializers[ctype].deserialize(response.body)['body']
        return data

    def serialize(self, data):
        ctype = 'application/%s' % self.fmt
        result = wsgi.Serializer().serialize(data, ctype)
        return result


class SubDictMatch:

    def __init__(self, sub_dict):
        self.sub_dict = sub_dict

    def __eq__(self, super_dict):
        return all(item in super_dict.items()
                   for item in self.sub_dict.items())
