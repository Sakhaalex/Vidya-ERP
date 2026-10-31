"""
Integration Tests - SQLite Adapter
Verifies SQLiteAdapter operations, transaction rollback atomicity,
foreign key enforcement, search pagination, and bulk error reporting.
"""
from decimal import Decimal
import unittest

from backend.adapters.sqlite.adapter import SQLiteAdapter
from backend.core_engine.contract import EngineConfig
from backend.core_engine.exceptions import (
    DataIntegrityError,
    DuplicateRecordError,
    NotFoundError,
)
from backend.core_engine.query import (
    FilterCondition,
    FilterOp,
    SortCriteria,
    SortDirection,
)
from backend.core_engine.types import (
    FieldDefinition,
    FieldType,
    SchemaDefinition,
)


class TestSQLiteAdapter(unittest.TestCase):

    def setUp(self):
        # In-memory SQLite for complete test isolation
        config = EngineConfig(adapter_name="sqlite", database=":memory:")
        self.adapter = SQLiteAdapter(config)
        self.adapter.connect()

        # Define test parent schema
        self.department_schema = SchemaDefinition(
            table_name="departments",
            fields={
                "id": FieldDefinition(name="id", field_type=FieldType.INTEGER, primary_key=True),
                "name": FieldDefinition(name="name", field_type=FieldType.TEXT, nullable=False, unique=True),
            }
        )

        # Define test child schema with foreign key
        self.employee_schema = SchemaDefinition(
            table_name="employees",
            fields={
                "id": FieldDefinition(name="id", field_type=FieldType.INTEGER, primary_key=True),
                "dept_id": FieldDefinition(
                    name="dept_id",
                    field_type=FieldType.REFERENCE,
                    reference_table="departments",
                    reference_column="id",
                    nullable=False,
                ),
                "name": FieldDefinition(name="name", field_type=FieldType.TEXT, nullable=False),
                "salary": FieldDefinition(name="salary", field_type=FieldType.DECIMAL, decimal_places=2),
                "is_active": FieldDefinition(name="is_active", field_type=FieldType.BOOLEAN, default=True),
            }
        )

        self.adapter.create_table(self.department_schema)
        self.adapter.create_table(self.employee_schema)

    def tearDown(self):
        self.adapter.disconnect()

    def test_health_check_and_capabilities(self):
        """Verifies health check probe and capability declaration."""
        health = self.adapter.health_check()
        self.assertTrue(health.is_healthy)
        self.assertGreaterEqual(health.latency_ms, 0)
        self.assertEqual(health.engine_name, "sqlite")

        caps = self.adapter.capability_report()
        self.assertEqual(caps.engine_name, "sqlite")
        self.assertTrue(caps.supports_savepoints)
        self.assertFalse(caps.supports_concurrent_writers)

    def test_crud_lifecycle(self):
        """Verifies insert, get, update, and delete."""
        # Insert department
        res = self.adapter.insert("departments", {"name": "Engineering"}, schema=self.department_schema)
        dept_id = res.record_id
        self.assertIsNotNone(dept_id)

        # Insert employee
        emp_res = self.adapter.insert(
            "employees",
            {"dept_id": dept_id, "name": "Alice Smith", "salary": "4500.00", "is_active": True},
            schema=self.employee_schema
        )
        emp_id = emp_res.record_id

        # Get
        emp = self.adapter.get("employees", emp_id, schema=self.employee_schema)
        self.assertIsNotNone(emp)
        self.assertEqual(emp["name"], "Alice Smith")
        self.assertEqual(emp["salary"], "4500.00")

        # Update
        up_res = self.adapter.update(
            "employees", emp_id, {"salary": "4800.00"}, schema=self.employee_schema
        )
        self.assertEqual(up_res.rows_affected, 1)

        updated_emp = self.adapter.get("employees", emp_id, schema=self.employee_schema)
        self.assertEqual(updated_emp["salary"], "4800.00")

        # Delete
        del_res = self.adapter.delete("employees", emp_id, schema=self.employee_schema)
        self.assertEqual(del_res.rows_affected, 1)
        self.assertIsNone(self.adapter.get("employees", emp_id, schema=self.employee_schema))

    def test_foreign_key_integrity_enforced(self):
        """Verifies PRAGMA foreign_keys = ON prevents dangling references."""
        with self.assertRaises(DataIntegrityError):
            self.adapter.insert(
                "employees",
                {"dept_id": 9999, "name": "Orphan Employee", "salary": "3000.00"},
                schema=self.employee_schema
            )

    def test_unique_constraint_enforced(self):
        """Verifies duplicate unique values raise DuplicateRecordError."""
        self.adapter.insert("departments", {"name": "Science"}, schema=self.department_schema)
        with self.assertRaises(DuplicateRecordError):
            self.adapter.insert("departments", {"name": "Science"}, schema=self.department_schema)

    def test_transaction_rollback_atomicity(self):
        """Verifies that on rollback, changes are undone completely."""
        tx = self.adapter.begin_transaction()
        self.adapter.insert("departments", {"name": "Finance"}, schema=self.department_schema, tx=tx)
        self.adapter.rollback_transaction(tx)

        # After rollback, Finance must NOT exist
        res = self.adapter.search(
            "departments",
            filters=[FilterCondition(column="name", operator=FilterOp.EQ, value="Finance")],
            schema=self.department_schema
        )
        self.assertEqual(res.total_count, 0)

    def test_search_pagination_and_sorting(self):
        """Verifies pagination and ordering."""
        # Insert 15 departments
        for i in range(15):
            self.adapter.insert("departments", {"name": f"Dept {i:02d}"}, schema=self.department_schema)

        # Page 1: limit 5, offset 0
        p1 = self.adapter.search(
            "departments",
            sort=[SortCriteria(column="name", direction=SortDirection.ASC)],
            limit=5,
            offset=0,
            schema=self.department_schema
        )
        self.assertEqual(p1.total_count, 15)
        self.assertEqual(len(p1.records), 5)
        self.assertEqual(p1.records[0]["name"], "Dept 00")

        # Page 2: limit 5, offset 5
        p2 = self.adapter.search(
            "departments",
            sort=[SortCriteria(column="name", direction=SortDirection.ASC)],
            limit=5,
            offset=5,
            schema=self.department_schema
        )
        self.assertEqual(len(p2.records), 5)
        self.assertEqual(p2.records[0]["name"], "Dept 05")


if __name__ == "__main__":
    unittest.main()
