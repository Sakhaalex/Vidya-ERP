"""
Vidya Data Engine - High-Level DataEngine Façade
Exposes stable, schema-aware, transaction-safe operations to application services.
Decouples application services from backend adapters.
"""
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Set

from backend.core_engine.capabilities import EngineCapabilities
from backend.core_engine.contract import (
    BulkOperationResult,
    EngineAdapterInterface,
    HealthReport,
    QueryResultSet,
    RecordResult,
)
from backend.core_engine.exceptions import NotFoundError, ValidationError
from backend.core_engine.query import FilterCondition, SortCriteria
from backend.core_engine.transaction import IsolationLevel, TransactionContext
from backend.core_engine.types import FieldDefinition, SchemaDefinition, TypeConverter


class DataEngine:
    """The central generic engine façade."""

    def __init__(self, adapter: EngineAdapterInterface):
        self.adapter = adapter
        self._schemas: Dict[str, SchemaDefinition] = {}

    def connect(self) -> None:
        self.adapter.connect()

    def disconnect(self) -> None:
        self.adapter.disconnect()

    def is_connected(self) -> bool:
        return self.adapter.is_connected()

    def health_check(self) -> HealthReport:
        return self.adapter.health_check()

    def capability_report(self) -> EngineCapabilities:
        return self.adapter.capability_report()

    def register_schema(self, schema: SchemaDefinition, auto_create_table: bool = False) -> None:
        """Register a known schema definition."""
        self._schemas[schema.table_name] = schema
        if auto_create_table and self.is_connected():
            self.adapter.create_table(schema)

    def get_schema(self, table_name: str) -> Optional[SchemaDefinition]:
        return self._schemas.get(table_name)

    def list_registered_tables(self) -> List[str]:
        return sorted(list(self._schemas.keys()))

    @contextmanager
    def begin(
        self,
        isolation_level: Optional[IsolationLevel] = None,
        read_only: bool = False
    ) -> Generator[TransactionContext, None, None]:
        """Context-managed atomic transaction."""
        tx = self.adapter.begin_transaction(isolation_level=isolation_level, read_only=read_only)
        try:
            yield tx
            if tx.active:
                self.adapter.commit_transaction(tx)
        except Exception:
            if tx.active:
                self.adapter.rollback_transaction(tx)
            raise

    def insert(
        self,
        table: str,
        values: Dict[str, Any],
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        schema = self._schemas.get(table)
        validated_values = self._validate_record(table, values, schema, is_update=False)
        return self.adapter.insert(table, validated_values, schema=schema, tx=tx)

    def get(
        self,
        table: str,
        record_id: Any,
        pk_column: str = "id",
        tx: Optional[TransactionContext] = None,
    ) -> Dict[str, Any]:
        schema = self._schemas.get(table)
        record = self.adapter.get(table, record_id, pk_column=pk_column, schema=schema, tx=tx)
        if record is None:
            raise NotFoundError(f"Record in '{table}' with {pk_column}={record_id} not found")
        return self._convert_output(schema, record)

    def get_or_none(
        self,
        table: str,
        record_id: Any,
        pk_column: str = "id",
        tx: Optional[TransactionContext] = None,
    ) -> Optional[Dict[str, Any]]:
        schema = self._schemas.get(table)
        record = self.adapter.get(table, record_id, pk_column=pk_column, schema=schema, tx=tx)
        if record is None:
            return None
        return self._convert_output(schema, record)

    def update(
        self,
        table: str,
        record_id: Any,
        changes: Dict[str, Any],
        pk_column: str = "id",
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        schema = self._schemas.get(table)
        validated_changes = self._validate_record(table, changes, schema, is_update=True)
        return self.adapter.update(
            table, record_id, validated_changes, pk_column=pk_column, schema=schema, tx=tx
        )

    def delete(
        self,
        table: str,
        record_id: Any,
        pk_column: str = "id",
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        schema = self._schemas.get(table)
        return self.adapter.delete(table, record_id, pk_column=pk_column, schema=schema, tx=tx)

    def search(
        self,
        table: str,
        filters: Optional[List[FilterCondition]] = None,
        sort: Optional[List[SortCriteria]] = None,
        limit: int = 50,
        offset: int = 0,
        columns: Optional[List[str]] = None,
        tx: Optional[TransactionContext] = None,
    ) -> QueryResultSet:
        schema = self._schemas.get(table)
        raw_result = self.adapter.search(
            table,
            filters=filters,
            sort=sort,
            limit=limit,
            offset=offset,
            columns=columns,
            schema=schema,
            tx=tx,
        )
        converted_records = [
            self._convert_output(schema, r) for r in raw_result.records
        ]
        return QueryResultSet(
            records=converted_records,
            total_count=raw_result.total_count,
            limit=raw_result.limit,
            offset=raw_result.offset,
        )

    def bulk_insert(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        tx: Optional[TransactionContext] = None,
    ) -> BulkOperationResult:
        schema = self._schemas.get(table)
        # Pre-validate each row
        validated_rows: List[Dict[str, Any]] = []
        row_errors: List[tuple[int, str]] = []

        for idx, row in enumerate(rows):
            try:
                val = self._validate_record(table, row, schema, is_update=False)
                validated_rows.append(val)
            except ValidationError as e:
                row_errors.append((idx, str(e)))

        if row_errors:
            # If any validation errors occur prior to insertion, report them
            return BulkOperationResult(
                success_count=0,
                error_count=len(row_errors),
                row_errors=row_errors,
                inserted_ids=[],
            )

        return self.adapter.bulk_insert(table, validated_rows, schema=schema, tx=tx)

    def _validate_record(
        self,
        table: str,
        values: Dict[str, Any],
        schema: Optional[SchemaDefinition],
        is_update: bool = False,
    ) -> Dict[str, Any]:
        """Runs portable type conversions and null/required checks."""
        if not schema:
            return dict(values)

        result: Dict[str, Any] = {}
        # Check for unknown fields
        for k in values.keys():
            if k not in schema.fields:
                raise ValidationError(f"Unknown field '{k}' for table '{table}'")

        # Validate provided fields
        for field_name, field_val in values.items():
            field_def = schema.fields[field_name]
            result[field_name] = TypeConverter.validate_and_convert(field_def, field_val)

        # For inserts, ensure required non-null fields with no default are supplied
        if not is_update:
            for field_name, field_def in schema.fields.items():
                if field_name not in result:
                    if field_def.default is not None:
                        result[field_name] = field_def.default
                    elif not field_def.nullable and not field_def.primary_key:
                        raise ValidationError(f"Field '{field_name}' in table '{table}' is required and cannot be null")

        return result

    def _convert_output(
        self,
        schema: Optional[SchemaDefinition],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Ensures types returned from adapter match expected python types."""
        if not schema or not record:
            return record

        converted: Dict[str, Any] = {}
        for k, v in record.items():
            field_def = schema.fields.get(k)
            if field_def:
                converted[k] = TypeConverter.validate_and_convert(field_def, v)
            else:
                converted[k] = v
        return converted
