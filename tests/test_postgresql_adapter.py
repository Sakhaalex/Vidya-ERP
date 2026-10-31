"""
Unit & Contract Tests - PostgreSQL Adapter
Tests PostgreSQL dialect generation, error code translations (SQLSTATE),
driver availability detection, and capability assertions.
Live connection tests gracefully skip if a live PostgreSQL server is unreachable.
"""
import unittest

from backend.adapters.postgresql.adapter import PostgreSQLAdapter
from backend.adapters.postgresql.dialect import PostgreSQLDialect
from backend.core_engine.contract import EngineConfig
from backend.core_engine.exceptions import (
    ConnectionUnavailableError,
    DataIntegrityError,
    DuplicateRecordError,
)
from backend.core_engine.types import (
    FieldDefinition,
    FieldType,
    SchemaDefinition,
)


class MockPostgresError(Exception):
    def __init__(self, message: str, sqlstate: str = None):
        super().__init__(message)
        self.sqlstate = sqlstate
        self.pgcode = sqlstate


class TestPostgreSQLAdapterUnit(unittest.TestCase):

    def test_ddl_generation(self):
        """Verifies PostgreSQL DDL mapping for exact money NUMERIC, TIMESTAMPTZ, JSONB."""
        schema = SchemaDefinition(
            table_name="fee_schedules",
            fields={
                "id": FieldDefinition(name="id", field_type=FieldType.INTEGER, primary_key=True),
                "title": FieldDefinition(name="title", field_type=FieldType.TEXT, max_length=100, nullable=False),
                "amount": FieldDefinition(name="amount", field_type=FieldType.DECIMAL, decimal_places=2, nullable=False),
                "is_mandatory": FieldDefinition(name="is_mandatory", field_type=FieldType.BOOLEAN, default=True),
                "created_at": FieldDefinition(name="created_at", field_type=FieldType.DATETIME),
                "metadata": FieldDefinition(name="metadata", field_type=FieldType.JSON_DATA),
            }
        )

        ddl = PostgreSQLDialect.generate_create_table_ddl(schema)
        self.assertIn('"id" BIGSERIAL PRIMARY KEY', ddl)
        self.assertIn('"title" VARCHAR(100) NOT NULL', ddl)
        self.assertIn('"amount" NUMERIC(14, 2) NOT NULL', ddl)
        self.assertIn('"is_mandatory" BOOLEAN DEFAULT TRUE', ddl)
        self.assertIn('"created_at" TIMESTAMPTZ', ddl)
        self.assertIn('"metadata" JSONB', ddl)

    def test_exception_mapping_sqlstate(self):
        """Verifies mapping of PostgreSQL SQLSTATE error codes to stable engine exceptions."""
        # 23505 = unique_violation
        err_23505 = MockPostgresError("Key (name)=(Engineering) already exists.", sqlstate="23505")
        mapped_dup = PostgreSQLDialect.map_exception(err_23505)
        self.assertIsInstance(mapped_dup, DuplicateRecordError)

        # 23503 = foreign_key_violation
        err_23503 = MockPostgresError("Key (dept_id)=(999) is not present in table.", sqlstate="23503")
        mapped_fk = PostgreSQLDialect.map_exception(err_23503)
        self.assertIsInstance(mapped_fk, DataIntegrityError)

        # 08006 = connection_failure
        err_08006 = MockPostgresError("Connection refused to 127.0.0.1:5432", sqlstate="08006")
        mapped_conn = PostgreSQLDialect.map_exception(err_08006)
        self.assertIsInstance(mapped_conn, ConnectionUnavailableError)

    def test_capability_report(self):
        """Verifies PostgreSQL capability declaration."""
        config = EngineConfig(adapter_name="postgresql", database="school_db")
        adapter = PostgreSQLAdapter(config)
        caps = adapter.capability_report()

        self.assertEqual(caps.engine_name, "postgresql")
        self.assertTrue(caps.supports_returning)
        self.assertTrue(caps.supports_concurrent_writers)
        self.assertTrue(caps.supports_json_type)
        self.assertIn("READ COMMITTED", caps.isolation_levels)
        self.assertIn("SERIALIZABLE", caps.isolation_levels)
        self.assertEqual(caps.storage_type, "network_service")

    def test_driver_handling(self):
        """Verifies clean handling when psycopg/psycopg2 is absent in environment."""
        config = EngineConfig(adapter_name="postgresql", database="test_db")
        adapter = PostgreSQLAdapter(config)

        # If driver module is missing, adapter.connect() must raise ConnectionUnavailableError
        # rather than letting an uncaught ImportError escape
        if adapter._get_driver_module() is None:
            with self.assertRaises(ConnectionUnavailableError) as ctx:
                adapter.connect()
            self.assertIn("PostgreSQL driver", str(ctx.exception))
        else:
            # If driver is installed, test connection failure to nonexistent DB
            with self.assertRaises(ConnectionUnavailableError):
                adapter.connect()


if __name__ == "__main__":
    unittest.main()
