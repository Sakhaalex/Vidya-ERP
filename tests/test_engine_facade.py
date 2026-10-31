"""
Integration Tests - DataEngine Façade (Non-School Domain)
Proves the generic Python data engine works completely independently of any
school-specific business logic or GUI code using an e-commerce catalog dataset.
"""
from decimal import Decimal
import unittest

from backend.adapters.sqlite.adapter import SQLiteAdapter
from backend.core_engine.contract import EngineConfig
from backend.core_engine.engine import DataEngine
from backend.core_engine.exceptions import (
    NotFoundError,
    ValidationError,
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


class TestDataEngineGenericFacade(unittest.TestCase):

    def setUp(self):
        config = EngineConfig(adapter_name="sqlite", database=":memory:")
        self.adapter = SQLiteAdapter(config)
        self.engine = DataEngine(self.adapter)
        self.engine.connect()

        # Non-school schema 1: Categories
        self.category_schema = SchemaDefinition(
            table_name="categories",
            fields={
                "id": FieldDefinition(name="id", field_type=FieldType.INTEGER, primary_key=True),
                "name": FieldDefinition(name="name", field_type=FieldType.TEXT, max_length=50, nullable=False),
            }
        )

        # Non-school schema 2: Products
        self.product_schema = SchemaDefinition(
            table_name="products",
            fields={
                "id": FieldDefinition(name="id", field_type=FieldType.INTEGER, primary_key=True),
                "category_id": FieldDefinition(
                    name="category_id",
                    field_type=FieldType.REFERENCE,
                    reference_table="categories",
                    reference_column="id",
                    nullable=False,
                ),
                "sku": FieldDefinition(name="sku", field_type=FieldType.TEXT, max_length=20, unique=True, nullable=False),
                "title": FieldDefinition(name="title", field_type=FieldType.TEXT, max_length=100, nullable=False),
                "unit_price": FieldDefinition(name="unit_price", field_type=FieldType.DECIMAL, decimal_places=2, nullable=False),
                "in_stock": FieldDefinition(name="in_stock", field_type=FieldType.BOOLEAN, default=True),
            }
        )

        self.engine.register_schema(self.category_schema, auto_create_table=True)
        self.engine.register_schema(self.product_schema, auto_create_table=True)

    def tearDown(self):
        self.engine.disconnect()

    def test_schema_registration_and_validation(self):
        """Verifies schema validation catches missing fields and unknown fields before DB."""
        cat_res = self.engine.insert("categories", {"name": "Hardware"})
        cat_id = cat_res.record_id

        # Insert with unknown field raises ValidationError
        with self.assertRaises(ValidationError) as ctx:
            self.engine.insert("products", {
                "category_id": cat_id,
                "sku": "HW-001",
                "title": "Hex Bolt",
                "unit_price": Decimal("2.50"),
                "unrecognized_field": 123
            })
        self.assertIn("Unknown field", str(ctx.exception))

        # Insert with float price is rejected by portable type system
        with self.assertRaises(ValidationError) as ctx:
            self.engine.insert("products", {
                "category_id": cat_id,
                "sku": "HW-001",
                "title": "Hex Bolt",
                "unit_price": 2.50
            })
        self.assertIn("cannot be initialized with float", str(ctx.exception))

    def test_context_managed_transaction_success(self):
        """Verifies multi-table atomic transaction commits successfully."""
        with self.engine.begin() as tx:
            c_res = self.engine.insert("categories", {"name": "Electronics"}, tx=tx)
            p_res = self.engine.insert("products", {
                "category_id": c_res.record_id,
                "sku": "ELEC-100",
                "title": "USB Cable",
                "unit_price": Decimal("15.99"),
                "in_stock": True,
            }, tx=tx)

        # Confirm persisted after transaction completes
        saved_product = self.engine.get("products", p_res.record_id)
        self.assertEqual(saved_product["sku"], "ELEC-100")
        self.assertEqual(saved_product["unit_price"], Decimal("15.99"))
        self.assertTrue(isinstance(saved_product["unit_price"], Decimal))

    def test_context_managed_transaction_rollback(self):
        """Verifies transaction rollback on unhandled error leaves zero changes."""
        try:
            with self.engine.begin() as tx:
                self.engine.insert("categories", {"name": "Books"}, tx=tx)
                # Intentionally trigger an exception mid-transaction
                raise RuntimeError("Simulated failure during checkout/order batch")
        except RuntimeError:
            pass

        # Verify 'Books' was rolled back completely
        results = self.engine.search(
            "categories",
            filters=[FilterCondition(column="name", operator=FilterOp.EQ, value="Books")]
        )
        self.assertEqual(results.total_count, 0)

    def test_search_and_decimal_types(self):
        """Verifies search with filters returns exact Decimal types."""
        c = self.engine.insert("categories", {"name": "Office"})
        self.engine.insert("products", {
            "category_id": c.record_id,
            "sku": "OFF-1",
            "title": "Paper Clips",
            "unit_price": Decimal("3.25"),
        })
        self.engine.insert("products", {
            "category_id": c.record_id,
            "sku": "OFF-2",
            "title": "Notebook",
            "unit_price": Decimal("8.50"),
        })

        search_res = self.engine.search(
            "products",
            filters=[FilterCondition(column="unit_price", operator=FilterOp.GT, value="5.00")],
            sort=[SortCriteria(column="unit_price", direction=SortDirection.DESC)],
        )

        self.assertEqual(search_res.total_count, 1)
        item = search_res.records[0]
        self.assertEqual(item["sku"], "OFF-2")
        self.assertEqual(item["unit_price"], Decimal("8.50"))

    def test_bulk_insert_validation(self):
        """Verifies bulk_insert detects invalid rows before inserting."""
        c = self.engine.insert("categories", {"name": "Tools"})

        batch = [
            {"category_id": c.record_id, "sku": "TOOL-1", "title": "Hammer", "unit_price": Decimal("24.00")},
            {"category_id": c.record_id, "sku": "TOOL-2", "title": "Pliers", "unit_price": 18.50},  # Invalid float!
        ]

        bulk_res = self.engine.bulk_insert("products", batch)
        self.assertEqual(bulk_res.success_count, 0)
        self.assertEqual(bulk_res.error_count, 1)
        self.assertEqual(bulk_res.row_errors[0][0], 1)
        self.assertIn("cannot be initialized with float", bulk_res.row_errors[0][1])


if __name__ == "__main__":
    unittest.main()
