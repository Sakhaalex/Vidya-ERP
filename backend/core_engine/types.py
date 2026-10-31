"""
Vidya Data Engine - Portable Type System & Validation
Maps logical schema types into backend-agnostic Python objects.
Enforces Decimal for money (never binary float), ISO-8601 for dates/times,
and strict validations before writes reach database drivers.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
import re
from typing import Any, Dict, List, Optional

from backend.core_engine.exceptions import ValidationError


class FieldType(str, Enum):
    """Portable field types supported across all database adapters."""
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"       # Currency and exact scientific calculation
    BOOLEAN = "boolean"
    DATE = "date"             # ISO-8601 YYYY-MM-DD
    TIME = "time"             # ISO-8601 HH:MM:SS
    DATETIME = "datetime"     # ISO-8601 with timezone (UTC normalized)
    JSON_DATA = "json"        # Structured dictionary or list
    REFERENCE = "reference"   # Foreign key to another table's primary key
    FILE_REF = "file_ref"     # Metadata reference to managed local file store


@dataclass(frozen=True)
class FieldDefinition:
    """Definition and constraints for a single table field."""
    name: str
    field_type: FieldType
    nullable: bool = True
    primary_key: bool = False
    unique: bool = False
    default: Optional[Any] = None
    max_length: Optional[int] = None
    min_value: Optional[Decimal | int] = None
    max_value: Optional[Decimal | int] = None
    decimal_places: int = 2
    reference_table: Optional[str] = None
    reference_column: Optional[str] = None
    on_delete: str = "RESTRICT"  # "RESTRICT", "CASCADE", "SET NULL"

    def __post_init__(self):
        # Validate identifier characters
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", self.name):
            raise ValidationError(f"Invalid field name identifier: '{self.name}'")


@dataclass
class SchemaDefinition:
    """Complete table schema definition."""
    table_name: str
    fields: Dict[str, FieldDefinition]
    indexes: List[List[str]] = field(default_factory=list)

    def __post_init__(self):
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$", self.table_name):
            raise ValidationError(f"Invalid table name identifier: '{self.table_name}'")
        pk_count = sum(1 for f in self.fields.values() if f.primary_key)
        if pk_count > 1:
            raise ValidationError(f"Composite primary keys not supported in portable engine: '{self.table_name}' has {pk_count}")

    @property
    def primary_key_field(self) -> Optional[FieldDefinition]:
        for f in self.fields.values():
            if f.primary_key:
                return f
        return None


class TypeConverter:
    """Validates and converts input values into strictly typed Python instances."""

    @staticmethod
    def validate_and_convert(field_def: FieldDefinition, value: Any) -> Any:
        """Validates and converts a value according to the field definition."""
        if value is None:
            if not field_def.nullable and not field_def.primary_key:
                raise ValidationError(f"Field '{field_def.name}' cannot be null")
            return None

        ft = field_def.field_type

        if ft == FieldType.TEXT:
            if not isinstance(value, str):
                val_str = str(value)
            else:
                val_str = value
            if field_def.max_length and len(val_str) > field_def.max_length:
                raise ValidationError(f"Field '{field_def.name}' exceeds maximum length of {field_def.max_length}")
            return val_str

        elif ft == FieldType.INTEGER:
            if isinstance(value, bool):
                raise ValidationError(f"Field '{field_def.name}' expected integer, got boolean")
            try:
                int_val = int(value)
            except (ValueError, TypeError):
                raise ValidationError(f"Field '{field_def.name}' must be a valid integer: received '{value}'")
            if field_def.min_value is not None and int_val < field_def.min_value:
                raise ValidationError(f"Field '{field_def.name}' value {int_val} below minimum {field_def.min_value}")
            if field_def.max_value is not None and int_val > field_def.max_value:
                raise ValidationError(f"Field '{field_def.name}' value {int_val} exceeds maximum {field_def.max_value}")
            return int_val

        elif ft == FieldType.DECIMAL:
            # Rejects float input directly to prevent floating-point inaccuracy for money
            if isinstance(value, float):
                raise ValidationError(
                    f"Field '{field_def.name}' of type DECIMAL cannot be initialized with float; use str or Decimal."
                )
            try:
                dec_val = Decimal(str(value)) if not isinstance(value, Decimal) else value
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(f"Field '{field_def.name}' must be a valid decimal amount: received '{value}'")
            # Quantize to required decimal places
            quantizer = Decimal("10") ** -field_def.decimal_places
            dec_val = dec_val.quantize(quantizer)
            if field_def.min_value is not None and dec_val < Decimal(str(field_def.min_value)):
                raise ValidationError(f"Field '{field_def.name}' amount {dec_val} below minimum {field_def.min_value}")
            if field_def.max_value is not None and dec_val > Decimal(str(field_def.max_value)):
                raise ValidationError(f"Field '{field_def.name}' amount {dec_val} exceeds maximum {field_def.max_value}")
            return dec_val

        elif ft == FieldType.BOOLEAN:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, str)):
                str_val = str(value).strip().lower()
                if str_val in ("1", "true", "t", "yes", "y"):
                    return True
                if str_val in ("0", "false", "f", "no", "n"):
                    return False
            raise ValidationError(f"Field '{field_def.name}' cannot convert '{value}' to boolean")

        elif ft == FieldType.DATE:
            if isinstance(value, date) and not isinstance(value, datetime):
                return value
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, str):
                try:
                    return date.fromisoformat(value.strip())
                except ValueError:
                    raise ValidationError(f"Field '{field_def.name}' must be ISO date (YYYY-MM-DD): received '{value}'")
            raise ValidationError(f"Field '{field_def.name}' cannot parse date from '{value}'")

        elif ft == FieldType.TIME:
            if isinstance(value, time):
                return value
            if isinstance(value, str):
                try:
                    return time.fromisoformat(value.strip())
                except ValueError:
                    raise ValidationError(f"Field '{field_def.name}' must be ISO time (HH:MM:SS): received '{value}'")
            raise ValidationError(f"Field '{field_def.name}' cannot parse time from '{value}'")

        elif ft == FieldType.DATETIME:
            if isinstance(value, datetime):
                # Normalize timezone to UTC
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)
            if isinstance(value, str):
                try:
                    iso_str = value.strip()
                    if iso_str.endswith("Z") or iso_str.endswith("z"):
                        iso_str = iso_str[:-1] + "+00:00"
                    parsed = datetime.fromisoformat(iso_str)
                    if parsed.tzinfo is None:
                        return parsed.replace(tzinfo=timezone.utc)
                    return parsed.astimezone(timezone.utc)
                except ValueError:
                    raise ValidationError(f"Field '{field_def.name}' must be ISO-8601 datetime: received '{value}'")
            raise ValidationError(f"Field '{field_def.name}' cannot parse datetime from '{value}'")

        elif ft == FieldType.JSON_DATA:
            if isinstance(value, (dict, list)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    raise ValidationError(f"Field '{field_def.name}' contains invalid JSON string: '{value}'")
            raise ValidationError(f"Field '{field_def.name}' requires dict, list, or JSON string")

        elif ft in (FieldType.REFERENCE, FieldType.FILE_REF):
            if isinstance(value, (int, str)):
                return value
            raise ValidationError(f"Field '{field_def.name}' must be an ID or reference key: received '{value}'")

        return value
