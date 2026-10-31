"""
Vidya Data Engine - Abstract Engine Contract
Defines the uniform interface that both SQLite and PostgreSQL adapters implement.
Guarantees consistent method signatures, return structures, and transaction handling.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.core_engine.capabilities import EngineCapabilities
from backend.core_engine.query import FilterCondition, SortCriteria
from backend.core_engine.transaction import IsolationLevel, TransactionContext
from backend.core_engine.types import SchemaDefinition


@dataclass
class EngineConfig:
    """Backend connection configuration."""
    adapter_name: str  # "sqlite" or "postgresql"
    database: str      # File path for SQLite, database name for PostgreSQL
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None
    pool_size: int = 5
    timeout_seconds: float = 30.0
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecordResult:
    """Result of an insert or update operation."""
    record_id: Optional[Any]
    rows_affected: int
    data: Optional[Dict[str, Any]] = None


@dataclass
class QueryResultSet:
    """Standardized result of a search or query operation."""
    records: List[Dict[str, Any]]
    total_count: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return (self.offset + len(self.records)) < self.total_count


@dataclass
class BulkOperationResult:
    """Detailed summary of bulk inserts/updates with row-level error reporting."""
    success_count: int
    error_count: int
    row_errors: List[Tuple[int, str]] = field(default_factory=list)
    inserted_ids: List[Any] = field(default_factory=list)


@dataclass
class HealthReport:
    """Result of backend health inspection."""
    is_healthy: bool
    latency_ms: float
    engine_name: str
    details: Dict[str, Any] = field(default_factory=dict)


class EngineAdapterInterface(ABC):
    """Abstract contract required for all concrete engine adapters."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection(s) to the underlying database."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Gracefully release all connections and resources."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection is alive and usable."""
        pass

    @abstractmethod
    def health_check(self) -> HealthReport:
        """Probe connection latency, read/write state, and return diagnostics."""
        pass

    @abstractmethod
    def capability_report(self) -> EngineCapabilities:
        """Report driver and database capabilities."""
        pass

    @abstractmethod
    def begin_transaction(
        self,
        isolation_level: Optional[IsolationLevel] = None,
        read_only: bool = False
    ) -> TransactionContext:
        """Start an explicit transaction context."""
        pass

    @abstractmethod
    def commit_transaction(self, tx: TransactionContext) -> None:
        """Commit an active transaction."""
        pass

    @abstractmethod
    def rollback_transaction(self, tx: TransactionContext) -> None:
        """Rollback an active transaction."""
        pass

    @abstractmethod
    def create_table(self, schema: SchemaDefinition, tx: Optional[TransactionContext] = None) -> None:
        """Create a table from a SchemaDefinition if it doesn't already exist."""
        pass

    @abstractmethod
    def drop_table(self, table_name: str, tx: Optional[TransactionContext] = None) -> None:
        """Drop a table if it exists."""
        pass

    @abstractmethod
    def list_tables(self, tx: Optional[TransactionContext] = None) -> List[str]:
        """Return names of all user tables in the database."""
        pass

    @abstractmethod
    def insert(
        self,
        table: str,
        values: Dict[str, Any],
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        """Insert a single record into table."""
        pass

    @abstractmethod
    def get(
        self,
        table: str,
        record_id: Any,
        pk_column: str = "id",
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single record by primary key."""
        pass

    @abstractmethod
    def update(
        self,
        table: str,
        record_id: Any,
        changes: Dict[str, Any],
        pk_column: str = "id",
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        """Update a single record by primary key."""
        pass

    @abstractmethod
    def delete(
        self,
        table: str,
        record_id: Any,
        pk_column: str = "id",
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> RecordResult:
        """Delete a record by primary key."""
        pass

    @abstractmethod
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
        """Execute a filtered, sorted, paginated query returning total count and records."""
        pass

    @abstractmethod
    def bulk_insert(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        schema: Optional[SchemaDefinition] = None,
        tx: Optional[TransactionContext] = None,
    ) -> BulkOperationResult:
        """Insert a list of records in a batch, with row-level validation."""
        pass
