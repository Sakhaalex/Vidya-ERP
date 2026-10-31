"""
Unit Tests - Safe Query Builder & Identifier Guard
Verifies SQL injection protection, identifier allow-listing,
and parameterized query plan generation.
"""
import unittest

from backend.core_engine.exceptions import SecurityViolationError, ValidationError
from backend.core_engine.query import (
    FilterCondition,
    FilterOp,
    IdentifierGuard,
    QueryBuilder,
    SortCriteria,
    SortDirection,
)


class TestQueryBuilderAndGuard(unittest.TestCase):

    def test_identifier_guard_valid(self):
        """Valid alphanumeric identifiers pass."""
        self.assertEqual(IdentifierGuard.validate("students"), "students")
        self.assertEqual(IdentifierGuard.validate("first_name_2"), "first_name_2")

    def test_identifier_guard_sql_injection_rejection(self):
        """Malicious SQL identifiers are immediately blocked."""
        malicious_inputs = [
            "students; DROP TABLE users;--",
            "students WHERE 1=1",
            "name' OR '1'='1",
            "table\"name",
            "column space",
            "-bad_dash",
            "",
        ]
        for bad in malicious_inputs:
            with self.assertRaises(SecurityViolationError):
                IdentifierGuard.validate(bad)

    def test_identifier_guard_allow_list(self):
        """Identifiers outside the allowed schema set are rejected."""
        allowed = {"id", "title", "price", "created_at"}
        self.assertEqual(IdentifierGuard.validate("price", allowed), "price")
        with self.assertRaises(SecurityViolationError):
            IdentifierGuard.validate("secret_token", allowed)

    def test_select_query_builder_sqlite(self):
        """Verifies SQLite parameterization with '?' placeholders."""
        qb = QueryBuilder(dialect="sqlite")
        plan = qb.build_select(
            table="invoices",
            columns=["id", "customer_id", "total_amount"],
            filters=[
                FilterCondition(column="status", operator=FilterOp.EQ, value="unpaid"),
                FilterCondition(column="total_amount", operator=FilterOp.GT, value=100),
            ],
            sort=[SortCriteria(column="created_at", direction=SortDirection.DESC)],
            limit=25,
            offset=50,
        )

        expected_sql = (
            'SELECT "id", "customer_id", "total_amount" FROM "invoices" '
            'WHERE "status" = ? AND "total_amount" > ? '
            'ORDER BY "created_at" DESC LIMIT 25 OFFSET 50'
        )
        self.assertEqual(plan.sql, expected_sql)
        self.assertEqual(plan.parameters, ("unpaid", 100))

    def test_select_query_builder_postgresql(self):
        """Verifies PostgreSQL parameterization with '%s' placeholders and ILIKE."""
        qb = QueryBuilder(dialect="postgresql")
        plan = qb.build_select(
            table="catalog_items",
            filters=[
                FilterCondition(column="name", operator=FilterOp.ILIKE, value="%stationery%"),
                FilterCondition(column="category_id", operator=FilterOp.IN, value=[1, 2, 3]),
            ],
            limit=10,
        )

        expected_sql = (
            'SELECT * FROM "catalog_items" '
            'WHERE "name" ILIKE %s AND "category_id" IN (%s, %s, %s) '
            'LIMIT 10'
        )
        self.assertEqual(plan.sql, expected_sql)
        self.assertEqual(plan.parameters, ("%stationery%", 1, 2, 3))


if __name__ == "__main__":
    unittest.main()
