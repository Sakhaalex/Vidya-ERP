"""
Unit Tests - Portable Type System & Validation
Verifies exact Decimal handling (rejecting float for money),
ISO date/time parsing, and schema constraint enforcement.
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal
import unittest

from backend.core_engine.exceptions import ValidationError
from backend.core_engine.types import (
    FieldDefinition,
    FieldType,
    SchemaDefinition,
    TypeConverter,
)


class TestPortableTypes(unittest.TestCase):

    def test_decimal_money_handling(self):
        """Verifies Decimal is required for currency and floats are rejected."""
        field_def = FieldDefinition(
            name="amount",
            field_type=FieldType.DECIMAL,
            decimal_places=2,
            min_value=Decimal("0.00"),
        )

        # Valid string decimal
        converted = TypeConverter.validate_and_convert(field_def, "1250.50")
        self.assertIsInstance(converted, Decimal)
        self.assertEqual(converted, Decimal("1250.50"))

        # Valid Decimal instance
        converted2 = TypeConverter.validate_and_convert(field_def, Decimal("99.9"))
        self.assertEqual(converted2, Decimal("99.90"))

        # CRITICAL: Rejection of binary float to prevent precision loss in financial totals
        with self.assertRaises(ValidationError) as ctx:
            TypeConverter.validate_and_convert(field_def, 1250.50)
        self.assertIn("cannot be initialized with float", str(ctx.exception))

        # Rejection of negative when min_value=0
        with self.assertRaises(ValidationError):
            TypeConverter.validate_and_convert(field_def, "-5.00")

    def test_text_and_max_length(self):
        """Verifies string validation and max length enforcement."""
        field_def = FieldDefinition(
            name="code",
            field_type=FieldType.TEXT,
            max_length=5,
        )
        self.assertEqual(TypeConverter.validate_and_convert(field_def, "ABC"), "ABC")
        with self.assertRaises(ValidationError) as ctx:
            TypeConverter.validate_and_convert(field_def, "TOOLONG123")
        self.assertIn("exceeds maximum length", str(ctx.exception))

    def test_date_and_datetime(self):
        """Verifies ISO-8601 parsing and UTC normalization."""
        date_def = FieldDefinition(name="due_date", field_type=FieldType.DATE)
        parsed_date = TypeConverter.validate_and_convert(date_def, "2026-11-15")
        self.assertEqual(parsed_date, date(2026, 11, 15))

        dt_def = FieldDefinition(name="created_at", field_type=FieldType.DATETIME)
        parsed_dt = TypeConverter.validate_and_convert(dt_def, "2026-11-15T10:30:00Z")
        self.assertEqual(parsed_dt.tzinfo, timezone.utc)
        self.assertEqual(parsed_dt.year, 2026)

        # Invalid date format
        with self.assertRaises(ValidationError):
            TypeConverter.validate_and_convert(date_def, "15/11/2026")

    def test_boolean_conversion(self):
        """Verifies canonical boolean normalization."""
        bool_def = FieldDefinition(name="is_active", field_type=FieldType.BOOLEAN)
        self.assertTrue(TypeConverter.validate_and_convert(bool_def, True))
        self.assertTrue(TypeConverter.validate_and_convert(bool_def, "true"))
        self.assertTrue(TypeConverter.validate_and_convert(bool_def, 1))
        self.assertFalse(TypeConverter.validate_and_convert(bool_def, False))
        self.assertFalse(TypeConverter.validate_and_convert(bool_def, "0"))
        self.assertFalse(TypeConverter.validate_and_convert(bool_def, "false"))

    def test_nullability_and_defaults(self):
        """Verifies non-nullable fields reject None."""
        req_def = FieldDefinition(name="title", field_type=FieldType.TEXT, nullable=False)
        with self.assertRaises(ValidationError):
            TypeConverter.validate_and_convert(req_def, None)

        opt_def = FieldDefinition(name="notes", field_type=FieldType.TEXT, nullable=True)
        self.assertIsNone(TypeConverter.validate_and_convert(opt_def, None))


if __name__ == "__main__":
    unittest.main()
