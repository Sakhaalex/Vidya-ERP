"""
Vidya Core Data Engine
Reusable, database-agnostic data platform.
"""
from backend.core_engine.capabilities import EngineCapabilities
from backend.core_engine.contract import (
    BulkOperationResult,
    EngineAdapterInterface,
    EngineConfig,
    HealthReport,
    QueryResultSet,
    RecordResult,
)
from backend.core_engine.engine import DataEngine
from backend.core_engine.exceptions import (
    ConflictError,
    ConnectionUnavailableError,
    DataEngineError,
    DataIntegrityError,
    DuplicateRecordError,
    MigrationError,
    NotFoundError,
    PermissionDeniedError,
    SecurityViolationError,
    ValidationError,
)
from backend.core_engine.query import (
    FilterCondition,
    FilterOp,
    IdentifierGuard,
    QueryBuilder,
    SortCriteria,
    SortDirection,
)
from backend.core_engine.transaction import IsolationLevel, TransactionContext
from backend.core_engine.types import (
    FieldDefinition,
    FieldType,
    SchemaDefinition,
    TypeConverter,
)

__all__ = [
    "DataEngine",
    "EngineAdapterInterface",
    "EngineConfig",
    "RecordResult",
    "QueryResultSet",
    "BulkOperationResult",
    "HealthReport",
    "EngineCapabilities",
    "DataEngineError",
    "ConnectionUnavailableError",
    "ValidationError",
    "NotFoundError",
    "DuplicateRecordError",
    "DataIntegrityError",
    "ConflictError",
    "PermissionDeniedError",
    "MigrationError",
    "SecurityViolationError",
    "FieldType",
    "FieldDefinition",
    "SchemaDefinition",
    "TypeConverter",
    "FilterOp",
    "FilterCondition",
    "SortDirection",
    "SortCriteria",
    "QueryBuilder",
    "IdentifierGuard",
    "IsolationLevel",
    "TransactionContext",
]
