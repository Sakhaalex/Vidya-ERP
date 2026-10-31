"""
Vidya SQLite Adapter - Concrete Implementation
Implements EngineAdapterInterface using Python's standard library sqlite3 driver.
Thread-safe, handles transactions with savepoints, and reports exact capabilities.
"""
from datetime import datetime
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Set

from backend.adapters.sqlite.dialect import SQLiteDialect
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


class SQLiteAdapter(EngineAdapterInterface):
    """SQLite implementation of the generic engine adapter contract."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self.query_builder = QueryBuilder(dialect="sqlite")

    def connect(self) -> None:
        with self._lock:
            if self._connection is not None:
                return

            database_path = self.config.database
            if database_path != ":memory:":
                # Ensure directory exists for file-based SQLite
                parent_dir = os.path.dirname(os.path.abspath(database_path))
                if parent_dir and not os.path.exists(parent_dir):
                    os.makedirs(parent_dir, exist_ok=True)

            try:
                # autocommit=False ensures manual transaction control
                conn = sqlite3.connect(
                    database_path,
                    timeout=self.config.timeout_seconds,
                    check_same_thread=False,
                    isolation_level=None  # Managed manually via BEGIN/COMMIT
                )
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("PRAGMA foreign_keys = ON;")
                cursor.execute("PRAGMA busy_timeout = 5000;")
                if database_path != ":memory:":
                    cursor.execute("PRAGMA journal_mode = WAL;")
                    cursor.execute("PRAGMA synchronous = NORMAL;")
                cursor.close()
                self._connection = conn
            except Exception as e:
                raise SQLiteDialect.map_exception(e)

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
                cur = self._connection.cursor()
                cur.execute("SELECT 1")
                cur.close()
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
                    engine_name="sqlite",
                    details={"error": "Not connected"}
                )
            try:
                cur = self._connection.cursor()
                cur.execute("PRAGMA foreign_keys;")
                fk_status = cur.fetchone()[0]
                cur.execute("SELECT sqlite_version();")
                version = cur.fetchone()[0]
                cur.close()
                latency = (time.perf_counter() - start_time) * 1000.0
                return HealthReport(
                    is_healthy=True,
                    latency_ms=round(latency, 2),
                    engine_name="sqlite",
                    details={
                        "version": version,
                        "database": self.config.database,
                        "foreign_keys_enabled": bool(fk_status),
                    }
                )
            except Exception as e:
                latency = (time.perf_counter() - start_time) * 1000.0
                return HealthReport(
                    is_healthy=False,
                    latency_ms=round(latency, 2),
                    engine_name="sqlite",
                    details={"error": str(e)}
                )

    def capability_report(self) -> EngineCapabilities:
        sqlite_ver = sqlite3.sqlite_version
        ver_parts = [int(p) for p in sqlite_ver.split(".")[:2]]
        # SQLite >= 3.35 supports RETURNING clause
        supports_returning = (ver_parts[0] > 3) or (ver_parts[0] == 3 and ver_parts[1] >= 35)

        return EngineCapabilities(
            engine_name="sqlite",
            engine_version=sqlite_ver,
            supports_returning=supports_returning,
            supports_savepoints=True,
            supports_case_insensitive_like=True,
            supports_json_type=True,
            supports_concurrent_writers=False,  # SQLite is single-writer per database file
            isolation_levels=["DEFERRED", "IMMEDIATE", "EXCLUSIVE"],
            supports_full_text_search=True,
            supports_ddl_transactions=True,
            storage_type="file" if self.config.database != ":memory:" else "memory",
        )

    def begin_transaction(
        self,
        isolation_level: Optional[IsolationLevel] = None,
        read_only: bool = False
    ) -> TransactionContext:
        with self._lock:
            self._ensure_connected()
            tx = TransactionContext(isolation_level=isolation_level, read_only=read_only)
            cursor = self._connection.cursor()
            try:
                iso = isolation_level.value if isolation_level else "IMMEDIATE"
                if iso not in ("DEFERRED", "IMMEDIATE", "EXCLUSIVE"):
                    iso = "IMMEDIATE"
                cursor.execute(f"BEGIN {iso};")
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()
            return tx

    def commit_transaction(self, tx: TransactionContext) -> None:
        with self._lock:
            self._ensure_connected()
            cursor = self._connection.cursor()
            try:
                cursor.execute("COMMIT;")
                tx.trigger_commit()
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

    def rollback_transaction(self, tx: TransactionContext) -> None:
        with self._lock:
            self._ensure_connected()
            cursor = self._connection.cursor()
            try:
                cursor.execute("ROLLBACK;")
                tx.trigger_rollback()
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

    def create_table(self, schema: SchemaDefinition, tx: Optional[TransactionContext] = None) -> None:
        with self._lock:
            self._ensure_connected()
            ddl = SQLiteDialect.generate_create_table_ddl(schema)
            cursor = self._connection.cursor()
            try:
                cursor.execute(ddl)
                # Create indexes if specified
                for idx_cols in schema.indexes:
                    idx_name = f"idx_{schema.table_name}_{'_'.join(idx_cols)}"
                    quoted_cols = ", ".join(IdentifierGuard.quote(c) for c in idx_cols)
                    cursor.execute(
                        f"CREATE INDEX IF NOT EXISTS {IdentifierGuard.quote(idx_name)} "
                        f"ON {IdentifierGuard.quote(schema.table_name)} ({quoted_cols});"
                    )
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

    def drop_table(self, table_name: str, tx: Optional[TransactionContext] = None) -> None:
        with self._lock:
            self._ensure_connected()
            safe_table = IdentifierGuard.quote(table_name)
            cursor = self._connection.cursor()
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {safe_table};")
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

    def list_tables(self, tx: Optional[TransactionContext] = None) -> List[str]:
        with self._lock:
            self._ensure_connected()
            cursor = self._connection.cursor()
            try:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
                )
                return [row[0] for row in cursor.fetchall()]
            finally:
                cursor.close()

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
            serialized = {k: SQLiteDialect.serialize_value(v) for k, v in values.items()}
            plan = self.query_builder.build_insert(table, serialized, allowed_columns=allowed)

            cursor = self._connection.cursor()
            try:
                cursor.execute(plan.sql, plan.parameters)
                rec_id = cursor.lastrowid
                return RecordResult(record_id=rec_id, rows_affected=cursor.rowcount, data=values)
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

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
            allowed = set(schema.fields.keys()) if schema else None
            safe_table = IdentifierGuard.quote(table)
            safe_pk = IdentifierGuard.quote(pk_column)
            sql = f"SELECT * FROM {safe_table} WHERE {safe_pk} = ? LIMIT 1"

            cursor = self._connection.cursor()
            try:
                cursor.execute(sql, (record_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                return dict(row)
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

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
            serialized = {k: SQLiteDialect.serialize_value(v) for k, v in changes.items()}
            plan = self.query_builder.build_update(
                table, serialized, pk_column, record_id, allowed_columns=allowed
            )

            cursor = self._connection.cursor()
            try:
                cursor.execute(plan.sql, plan.parameters)
                if cursor.rowcount == 0:
                    raise NotFoundError(f"Record in '{table}' with {pk_column}={record_id} not found for update")
                return RecordResult(record_id=record_id, rows_affected=cursor.rowcount, data=changes)
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

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

            cursor = self._connection.cursor()
            try:
                cursor.execute(plan.sql, plan.parameters)
                if cursor.rowcount == 0:
                    raise NotFoundError(f"Record in '{table}' with {pk_column}={record_id} not found for delete")
                return RecordResult(record_id=record_id, rows_affected=cursor.rowcount)
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

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

            # Serialize filter parameters
            safe_filters: Optional[List[FilterCondition]] = None
            if filters:
                safe_filters = []
                for f in filters:
                    v1 = SQLiteDialect.serialize_value(f.value)
                    v2 = SQLiteDialect.serialize_value(f.second_value) if f.second_value is not None else None
                    safe_filters.append(FilterCondition(column=f.column, operator=f.operator, value=v1, second_value=v2))

            count_plan = self.query_builder.build_count(table, safe_filters, allowed_columns=allowed)
            select_plan = self.query_builder.build_select(
                table,
                columns=columns,
                filters=safe_filters,
                sort=sort,
                limit=limit,
                offset=offset,
                allowed_columns=allowed,
            )

            cursor = self._connection.cursor()
            try:
                cursor.execute(count_plan.sql, count_plan.parameters)
                total = cursor.fetchone()[0]

                cursor.execute(select_plan.sql, select_plan.parameters)
                rows = [dict(r) for r in cursor.fetchall()]

                return QueryResultSet(records=rows, total_count=total, limit=limit, offset=offset)
            except Exception as e:
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

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

            # Wrap in savepoint if in existing tx, or begin immediate if not
            owns_tx = (tx is None)
            active_tx = tx or self.begin_transaction()
            inserted_ids: List[Any] = []
            row_errors: List[tuple[int, str]] = []

            cursor = self._connection.cursor()
            try:
                for idx, row in enumerate(rows):
                    try:
                        ser_row = {k: SQLiteDialect.serialize_value(v) for k, v in row.items()}
                        plan = self.query_builder.build_insert(table, ser_row, allowed_columns=allowed)
                        cursor.execute(plan.sql, plan.parameters)
                        inserted_ids.append(cursor.lastrowid)
                    except Exception as err:
                        mapped = SQLiteDialect.map_exception(err)
                        row_errors.append((idx, str(mapped)))

                if row_errors:
                    # Rollback on partial failure to maintain batch atomicity
                    if owns_tx:
                        self.rollback_transaction(active_tx)
                    return BulkOperationResult(
                        success_count=0,
                        error_count=len(row_errors),
                        row_errors=row_errors,
                        inserted_ids=[],
                    )

                if owns_tx:
                    self.commit_transaction(active_tx)

                return BulkOperationResult(
                    success_count=len(rows),
                    error_count=0,
                    row_errors=[],
                    inserted_ids=inserted_ids,
                )
            except Exception as e:
                if owns_tx:
                    self.rollback_transaction(active_tx)
                raise SQLiteDialect.map_exception(e)
            finally:
                cursor.close()

    def _ensure_connected(self) -> None:
        if self._connection is None:
            self.connect()
