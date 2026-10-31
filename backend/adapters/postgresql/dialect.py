"""
Vidya PostgreSQL Adapter - Dialect & Type Mapping
Generates standard PostgreSQL DDL and maps psycopg/psycopg2 exceptions.
"""
from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend.core_engine.exceptions import (
    ConnectionUnavailableError,
    DataIntegrityError,
    DuplicateRecordError,
    SecurityViolationError,
)
from backend.core_engine.query import IdentifierGuard
from backend.core_engine.types import FieldDefinition, FieldType, SchemaDefinition


class PostgreSQLDialect:
    """PostgreSQL dialect helper for DDL generation and error translation."""

    TYPE_MAP = {
        FieldType.TEXT: "TEXT",
        FieldType.INTEGER: "BIGINT",
        FieldType.DECIMAL: "NUMERIC",    # Exact numeric handling
        FieldType.BOOLEAN: "BOOLEAN",
        FieldType.DATE: "DATE",
        FieldType.TIME: "TIME WITHOUT TIME ZONE",
        FieldType.DATETIME: "TIMESTAMPTZ",
        FieldType.JSON_DATA: "JSONB",
        FieldType.REFERENCE: "BIGINT",
        FieldType.FILE_REF: "VARCHAR(64)",
    }

    @classmethod
    def generate_create_table_ddl(cls, schema: SchemaDefinition) -> str:
        table_name = IdentifierGuard.quote(schema.table_name)
        col_defs: List[str] = []
        fk_defs: List[str] = []

        for field_def in schema.fields.values():
            col_name = IdentifierGuard.quote(field_def.name)

            if field_def.primary_key:
                if field_def.field_type == FieldType.INTEGER:
                    col_type = "BIGSERIAL PRIMARY KEY"
                else:
                    col_type = f"{cls.TYPE_MAP.get(field_def.field_type, 'TEXT')} PRIMARY KEY"
                col_defs.append(f"{col_name} {col_type}")
                continue

            if field_def.field_type == FieldType.DECIMAL:
                col_type = f"NUMERIC(14, {field_def.decimal_places})"
            elif field_def.field_type == FieldType.TEXT and field_def.max_length:
                col_type = f"VARCHAR({field_def.max_length})"
            else:
                col_type = cls.TYPE_MAP.get(field_def.field_type, "TEXT")

            parts = [col_name, col_type]
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
                    parts.append(f"DEFAULT {str(def_val).upper()}")
                else:
                    parts.append(f"DEFAULT {def_val}")

            col_defs.append(" ".join(parts))

            # Foreign key constraint
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
        return f"CREATE TABLE IF NOT EXISTS {table_name} (\n  " + ",\n  ".join(all_defs) + "\n);"

    @staticmethod
    def map_exception(err: Exception) -> Exception:
        """Translates psycopg/psycopg2 exceptions into stable DataEngine errors."""
        msg = str(err)
        err_type = type(err).__name__

        # Check PostgreSQL SQLSTATE if available
        sqlstate = getattr(err, "pgcode", None) or getattr(err, "sqlstate", None)

        if sqlstate:
            # Class 23: Integrity Constraint Violation
            if sqlstate == "23505":  # unique_violation
                return DuplicateRecordError(f"Unique constraint violated: {msg}")
            if sqlstate == "23503":  # foreign_key_violation
                return DataIntegrityError(f"Foreign key constraint failed: {msg}")
            if sqlstate == "23502":  # not_null_violation
                return DataIntegrityError(f"Non-nullable field constraint failed: {msg}")
            if sqlstate == "23514":  # check_violation
                return DataIntegrityError(f"Check constraint failed: {msg}")

            # Class 08: Connection Exception
            if sqlstate.startswith("08"):
                return ConnectionUnavailableError(f"PostgreSQL connection error: {msg}")

            # Class 40: Transaction Rollback (deadlock, serialization failure)
            if sqlstate in ("40001", "40P01"):
                return ConflictError(f"PostgreSQL serialization/deadlock failure: {msg}")

        # String matching fallback
        if "unique" in msg.lower() or "duplicate key" in msg.lower():
            return DuplicateRecordError(f"Unique constraint violated: {msg}")
        if "foreign key" in msg.lower():
            return DataIntegrityError(f"Foreign key constraint failed: {msg}")
        if "not-null" in msg.lower():
            return DataIntegrityError(f"Non-nullable field constraint failed: {msg}")
        if "could not connect" in msg.lower() or "connection refused" in msg.lower():
            return ConnectionUnavailableError(f"PostgreSQL connection unavailable: {msg}")

        return ConnectionUnavailableError(f"PostgreSQL error [{err_type}]: {msg}")
