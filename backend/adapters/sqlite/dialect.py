"""
Vidya SQLite Adapter - Dialect & Type Mapping
Converts portable FieldDefinitions to SQLite DDL and maps exceptions.
"""
from decimal import Decimal
import re
import sqlite3
from typing import Any, Dict, List, Optional

from backend.core_engine.exceptions import (
    ConnectionUnavailableError,
    DataIntegrityError,
    DuplicateRecordError,
    SecurityViolationError,
)
from backend.core_engine.query import IdentifierGuard
from backend.core_engine.types import FieldDefinition, FieldType, SchemaDefinition


class SQLiteDialect:
    """SQLite dialect helper for DDL generation and error translation."""

    TYPE_MAP = {
        FieldType.TEXT: "TEXT",
        FieldType.INTEGER: "INTEGER",
        FieldType.DECIMAL: "TEXT",       # Stored as TEXT for guaranteed exactness without float rounding
        FieldType.BOOLEAN: "INTEGER",    # 0 or 1
        FieldType.DATE: "TEXT",          # ISO YYYY-MM-DD
        FieldType.TIME: "TEXT",          # ISO HH:MM:SS
        FieldType.DATETIME: "TEXT",      # ISO UTC timestamp
        FieldType.JSON_DATA: "TEXT",     # JSON string
        FieldType.REFERENCE: "INTEGER",  # FK target ID
        FieldType.FILE_REF: "TEXT",      # File key reference
    }

    @classmethod
    def generate_create_table_ddl(cls, schema: SchemaDefinition) -> str:
        table_name = IdentifierGuard.quote(schema.table_name)
        col_defs: List[str] = []
        fk_defs: List[str] = []

        for field_def in schema.fields.values():
            col_name = IdentifierGuard.quote(field_def.name)
            col_type = cls.TYPE_MAP.get(field_def.field_type, "TEXT")

            parts = [col_name, col_type]

            if field_def.primary_key:
                parts.append("PRIMARY KEY")
                if field_def.field_type == FieldType.INTEGER:
                    parts.append("AUTOINCREMENT")
            else:
                if not field_def.nullable:
                    parts.append("NOT NULL")
                if field_def.unique:
                    parts.append("UNIQUE")
                if field_def.default is not None:
                    def_val = field_def.default
                    if isinstance(def_val, str):
                        def_val_escaped = def_val.replace("'", "''")
                        parts.append(f"DEFAULT '{def_val_escaped}'")
                    elif isinstance(def_val, bool):
                        parts.append(f"DEFAULT {1 if def_val else 0}")
                    else:
                        parts.append(f"DEFAULT {def_val}")

            col_defs.append(" ".join(parts))

            # Foreign key constraint if reference
            if field_def.reference_table and field_def.reference_column:
                ref_tbl = IdentifierGuard.quote(field_def.reference_table)
                ref_col = IdentifierGuard.quote(field_def.reference_column)
                on_delete = field_def.on_delete.upper()
                if on_delete not in ("CASCADE", "RESTRICT", "SET NULL", "NO ACTION"):
                    on_delete = "RESTRICT"
                fk_defs.append(
                    f"FOREIGN KEY ({col_name}) REFERENCES {ref_tbl}({ref_col}) ON DELETE {on_delete}"
                )

        all_defs = col_defs + fk_defs
        return f"CREATE TABLE IF NOT EXISTS {table_name} (\n  " + ",\n  ".join(all_defs) + "\n)"

    @staticmethod
    def map_exception(err: Exception) -> Exception:
        """Translates sqlite3 exceptions into stable DataEngine errors."""
        msg = str(err)
        if isinstance(err, sqlite3.IntegrityError):
            if "UNIQUE constraint failed" in msg or "PRIMARY KEY must be unique" in msg:
                return DuplicateRecordError(f"Unique constraint violated: {msg}")
            if "FOREIGN KEY constraint failed" in msg:
                return DataIntegrityError(f"Foreign key constraint failed: {msg}")
            if "NOT NULL constraint failed" in msg:
                return DataIntegrityError(f"Non-nullable field constraint failed: {msg}")
            if "CHECK constraint failed" in msg:
                return DataIntegrityError(f"Check constraint failed: {msg}")
            return DataIntegrityError(f"Integrity constraint failed: {msg}")

        if isinstance(err, sqlite3.OperationalError):
            if "locked" in msg or "busy" in msg:
                return ConnectionUnavailableError(f"SQLite database is busy or locked: {msg}")
            if "no such table" in msg:
                return DataIntegrityError(f"Table does not exist: {msg}")
            return ConnectionUnavailableError(f"SQLite operational error: {msg}")

        return err

    @staticmethod
    def serialize_value(val: Any) -> Any:
        """Converts Python value to SQLite-storable representation."""
        if val is None:
            return None
        if isinstance(val, Decimal):
            return str(val)
        if isinstance(val, bool):
            return 1 if val else 0
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return val
