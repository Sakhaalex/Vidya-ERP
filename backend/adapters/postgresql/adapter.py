"""
Vidya PostgreSQL Adapter - Concrete Implementation
Implements EngineAdapterInterface for PostgreSQL using psycopg / psycopg2.
Encapsulates connection lifecycle, transaction isolation, and PostgreSQL capability reporting.
"""
from datetime import datetime
from decimal import Decimal
import threading
import time
from typing import Any, Dict, List, Optional, Set

from backend.adapters.postgresql.dialect import PostgreSQLDialect
from backend.core_engine.capabilities import EngineCapabilities
from backend.core_engine.contract import (
    BulkOperationResult,
    EngineAdapterInterface,
    EngineConfig,
    HealthReport,
    QueryResultSet,
    RecordResult,
)
from backend.core_engine.exceptions import (
    ConnectionUnavailableError,
    DataEngineError,
    NotFoundError,
    ValidationError,
)
from backend.core_engine.query import (
    FilterCondition,
    IdentifierGuard,
    QueryBuilder,
    SortCriteria,
)
from backend.core_engine.transaction import IsolationLevel, TransactionContext
from backend.core_engine.types import SchemaDefinition


class PostgreSQLAdapter(EngineAdapterInterface):
    """PostgreSQL implementation of the generic engine adapter contract."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self._connection: Optional[Any] = None
        self._driver: Optional[str] = None
        self._lock = threading.RLock()
        self.query_builder = QueryBuilder(dialect="postgresql")

    def _get_driver_module(self) -> Any:
        """Attempt to import psycopg (v3) or psycopg2."""
        try:
            import psycopg
            self._driver = "psycopg"
            return psycopg
        except ImportError:
            pass

        try:
            import psycopg2
            from psycopg2 import extras
            self._driver = "psycopg2"
            return psycopg2
        except ImportError:
            pass

        return None

    def connect(self) -> None:
        with self._lock:
            if self._connection is not None:
                return

            driver = self._get_driver_module()
            if driver is None:
                raise ConnectionUnavailableError(
                    "PostgreSQL driver ('psycopg' or 'psycopg2') is not installed in the Python environment."
                )

            try:
                # Connection params
                conn_kwargs = {
                    "dbname": self.config.database,
                    "host": self.config.host or "localhost",
                    "port": self.config.port or 5432,
                    "connect_timeout": int(self.config.timeout_seconds),
                }
                if self.config.user:
                    conn_kwargs["user"] = self.config.user
                if self.config.password:
                    conn_kwargs["password"] = self.config.password

                if self._driver == "psycopg":
                    self._connection = driver.connect(**conn_kwargs, autocommit=False)
                else:
                    self._connection = driver.connect(**conn_kwargs)
                    self._connection.autocommit = False

            except Exception as e:
                raise PostgreSQLDialect.map_exception(e)

    def disconnect(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    pass
                finally:
                    self._connection = None

    def is_connected(self) -> bool:
        with self._lock:
            if self._connection is None:
                return False
            try:
                with self._connection.cursor() as cur:
                    cur.execute("SELECT 1;")
                return True
            except Exception:
                return False

    def health_check(self) -> HealthReport:
        start_time = time.perf_counter()
        with self._lock:
            if self._connection is None:
                return HealthReport(
                    is_healthy=False,
                    latency_ms=-1.0,
                    engine_name="postgresql",
                    details={"error": "Not connected", "driver": self._driver or "none"}
                )
            try:
                with self._connection.cursor() as cur:
                    cur.execute("SELECT version();")
                    row = cur.fetchone()
                    pg_version = row[0] if row else "unknown"

                latency = (time.perf_counter() - start_time) * 1000.0
                return HealthReport(
                    is_healthy=True,
                    latency_ms=round(latency, 2),
                    engine_name="postgresql",
                    details={
                        "version": pg_version,
                        "database": self.config.database,
                        "driver": self._driver,
                        "host": self.config.host,
                        "port": self.config.port,
                    }
                )
            except Exception as e:
                latency = (time.perf_counter() - start_time) * 1000.0
                return HealthReport(
                    is_healthy=False,
                    latency_ms=round(latency, 2),
                    engine_name="postgresql",
                    details={"error": str(e), "driver": self._driver}
                )

    def capability_report(self) -> EngineCapabilities:
        return EngineCapabilities(
            engine_name="postgresql",
            engine_version="PostgreSQL Standard (psycopg/psycopg2)",
            supports_returning=True,
            supports_savepoints=True,
            supports_case_insensitive_like=True,
            supports_json_type=True,
            supports_concurrent_writers=True,
            isolation_levels=["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"],
            supports_full_text_search=True,
            supports_ddl_transactions=True,
            storage_type="network_service",
        )

    def begin_transaction(
        self,
        isolation_level: Optional[IsolationLevel] = None,
        read_only: bool = False
    ) -> TransactionContext:
        with self._lock:
            self._ensure_connected()
            tx = TransactionContext(isolation_level=isolation_level, read_only=read_only)
            try:
                with self._connection.cursor() as cur:
                    iso_str = isolation_level.value if isolation_level else "READ COMMITTED"
                    if iso_str not in ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"):
                        iso_str = "READ COMMITTED"
                    cur.execute(f"SET TRANSACTION ISOLATION LEVEL {iso_str};")
                    if read_only:
                        cur.execute("SET TRANSACTION READ ONLY;")
            except Exception as e:
                raise PostgreSQLDialect.map_exception(e)
            return tx

    def commit_transaction(self, tx: TransactionContext) -> None:
        with self._lock:
            self._ensure_connected()
            try:
                self._connection.commit()
                tx.trigger_commit()
            except Exception as e:
                raise PostgreSQLDialect.map_exception(e)

    def rollback_transaction(self, tx: TransactionContext) -> None:
        with self._lock:
            self._ensure_connected()
            try:
                self._connection.rollback()
                tx.trigger_rollback()
            except Exception as e:
                raise PostgreSQLDialect.map_exception(e)

    def create_table(self, schema: SchemaDefinition, tx: Optional[TransactionContext] = None) -> None:
        with self._lock:
            self._ensure_connected()
            ddl = PostgreSQLDialect.generate_create_table_ddl(schema)
            try:
                with self._connection.cursor() as cur:
                    cur.execute(ddl)
                    # Create indexes
                    for idx_cols in schema.indexes:
                        idx_name = f"idx_{schema.table_name}_{'_'.join(idx_cols)}"
                        quoted_cols = ", ".join(IdentifierGuard.quote(c) for c in idx_cols)
                        cur.execute(
                            f"CREATE INDEX IF NOT EXISTS {IdentifierGuard.quote(idx_name)} "
                            f"ON {IdentifierGuard.quote(schema.table_name)} ({quoted_cols});"
                        )
                if tx is None:
                    self._connection.commit()
            except Exception as e:
                if tx is None:
                    self._connection.rollback()
                raise PostgreSQLDialect.map_exception(e)

    def drop_table(self, table_name: str, tx: Optional[TransactionContext] = None) -> None:
        with self._lock:
            self._ensure_connected()
            safe_table = IdentifierGuard.quote(table_name)
            try:
                with self._connection.cursor() as cur:
                    cur.execute(f"DROP TABLE IF EXISTS {safe_table} CASCADE;")
                if tx is None:
                    self._connection.commit()
            except Exception as e:
                if tx is None:
                    self._connection.rollback()
                raise PostgreSQLDialect.map_exception(e)

    def list_tables(self, tx: Optional[TransactionContext] = None) -> List[str]:
        with self._lock:
            self._ensure_connected()
            try:
                with self._connection.cursor() as cur:
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                        "ORDER BY table_name;"
                    )
                    return [row[0] for row in cur.fetchall()]
            except Exception as e:
                raise PostgreSQLDialect.map_exception(e)

    def insert(
        self,
        table: str,
        values: Dict[str, Any],
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        with self._lock:
            self._ensure_connected()
            allowed = set(schema.fields.keys()) if schema else None
            pk_name = schema.primary_key_field.name if schema and schema.primary_key_field else "id"

            plan = self.query_builder.build_insert(
                table, values, returning_col=pk_name, allowed_columns=allowed
            )
            try:
                with self._connection.cursor() as cur:
                    cur.execute(plan.sql, plan.parameters)
                    row = cur.fetchone()
                    rec_id = row[0] if row else None
                if tx is None:
                    self._connection.commit()
                return RecordResult(record_id=rec_id, rows_affected=1, data=values)
            except Exception as e:
                if tx is None:
                    self._connection.rollback()
                raise PostgreSQLDialect.map_exception(e)

    def get(
        self,
        table: str,
        record_id: Any,
        pk_column: str = "id",
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_connected()
            safe_table = IdentifierGuard.quote(table)
            safe_pk = IdentifierGuard.quote(pk_column)
            sql = f"SELECT * FROM {safe_table} WHERE {safe_pk} = %s LIMIT 1"

            try:
                with self._connection.cursor() as cur:
                    cur.execute(sql, (record_id,))
                    row = cur.fetchone()
                    if row is None:
                        return None
                    col_names = [desc[0] for desc in cur.description]
                    return dict(zip(col_names, row))
            except Exception as e:
                raise PostgreSQLDialect.map_exception(e)

    def update(
        self,
        table: str,
        record_id: Any,
        changes: Dict[str, Any],
        pk_column: str = "id",
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        with self._lock:
            self._ensure_connected()
            allowed = set(schema.fields.keys()) if schema else None
            plan = self.query_builder.build_update(
                table, changes, pk_column, record_id, allowed_columns=allowed
            )
            try:
                with self._connection.cursor() as cur:
                    cur.execute(plan.sql, plan.parameters)
                    affected = cur.rowcount
                if affected == 0:
                    raise NotFoundError(f"Record in '{table}' with {pk_column}={record_id} not found for update")
                if tx is None:
                    self._connection.commit()
                return RecordResult(record_id=record_id, rows_affected=affected, data=changes)
            except Exception as e:
                if tx is None:
                    self._connection.rollback()
                raise PostgreSQLDialect.map_exception(e)

    def delete(
        self,
        table: str,
        record_id: Any,
        pk_column: str = "id",
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        with self._lock:
            self._ensure_connected()
            allowed = set(schema.fields.keys()) if schema else None
            plan = self.query_builder.build_delete(table, pk_column, record_id, allowed_columns=allowed)
            try:
                with self._connection.cursor() as cur:
                    cur.execute(plan.sql, plan.parameters)
                    affected = cur.rowcount
                if affected == 0:
                    raise NotFoundError(f"Record in '{table}' with {pk_column}={record_id} not found for delete")
                if tx is None:
                    self._connection.commit()
                return RecordResult(record_id=record_id, rows_affected=affected)
            except Exception as e:
                if tx is None:
                    self._connection.rollback()
                raise PostgreSQLDialect.map_exception(e)

    def search(
        self,
        table: str,
        filters: Optional[List[FilterCondition]] = None,
        sort: Optional[List[SortCriteria]] = None,
        limit: int = 50,
        offset: int = 0,
        columns: Optional[List[str]] = None,
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> QueryResultSet:
        with self._lock:
            self._ensure_connected()
            allowed = set(schema.fields.keys()) if schema else None

            count_plan = self.query_builder.build_count(table, filters, allowed_columns=allowed)
            select_plan = self.query_builder.build_select(
                table,
                columns=columns,
                filters=filters,
                sort=sort,
                limit=limit,
                offset=offset,
                allowed_columns=allowed,
            )

            try:
                with self._connection.cursor() as cur:
                    cur.execute(count_plan.sql, count_plan.parameters)
                    total = cur.fetchone()[0]

                    cur.execute(select_plan.sql, select_plan.parameters)
                    col_names = [desc[0] for desc in cur.description]
                    records = [dict(zip(col_names, r)) for r in cur.fetchall()]

                return QueryResultSet(records=records, total_count=total, limit=limit, offset=offset)
            except Exception as e:
                raise PostgreSQLDialect.map_exception(e)

    def bulk_insert(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> BulkOperationResult:
        if not rows:
            return BulkOperationResult(success_count=0, error_count=0)

        with self._lock:
            self._ensure_connected()
            allowed = set(schema.fields.keys()) if schema else None
            pk_name = schema.primary_key_field.name if schema and schema.primary_key_field else "id"

            owns_tx = (tx is None)
            inserted_ids: List[Any] = []
            row_errors: List[tuple[int, str]] = []

            try:
                with self._connection.cursor() as cur:
                    for idx, row in enumerate(rows):
                        try:
                            plan = self.query_builder.build_insert(
                                table, row, returning_col=pk_name, allowed_columns=allowed
                            )
                            cur.execute(plan.sql, plan.parameters)
                            res = cur.fetchone()
                            inserted_ids.append(res[0] if res else None)
                        except Exception as err:
                            mapped = PostgreSQLDialect.map_exception(err)
                            row_errors.append((idx, str(mapped)))

                if row_errors:
                    if owns_tx:
                        self._connection.rollback()
                    return BulkOperationResult(
                        success_count=0,
                        error_count=len(row_errors),
                        row_errors=row_errors,
                        inserted_ids=[],
                    )

                if owns_tx:
                    self._connection.commit()

                return BulkOperationResult(
                    success_count=len(rows),
                    error_count=0,
                    row_errors=[],
                    inserted_ids=inserted_ids,
                )
            except Exception as e:
                if owns_tx:
                    self._connection.rollback()
                raise PostgreSQLDialect.map_exception(e)

    def _ensure_connected(self) -> None:
        if self._connection is None:
            self.connect()
