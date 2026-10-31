"""
Vidya Data Engine - Core Exceptions
Defines stable, backend-agnostic exception hierarchy.
"""

class DataEngineError(Exception):
    """Base exception for all Vidya Data Engine errors."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConnectionUnavailableError(DataEngineError):
    """Raised when the database connection cannot be established or is lost."""
    pass


class ValidationError(DataEngineError):
    """Raised when data fails portable schema validation or constraint checks."""
    def __init__(self, message: str, field_errors: dict[str, str] = None, details: dict = None):
        super().__init__(message, details)
        self.field_errors = field_errors or {}


class NotFoundError(DataEngineError):
    """Raised when a requested record or table cannot be found."""
    pass


class DuplicateRecordError(DataEngineError):
    """Raised when an operation violates a unique constraint or primary key."""
    pass


class DataIntegrityError(DataEngineError):
    """Raised when an operation violates foreign key, check constraint, or nullability."""
    pass


class ConflictError(DataEngineError):
    """Raised when a concurrent edit conflict or locking collision occurs."""
    pass


class PermissionDeniedError(DataEngineError):
    """Raised when an operation violates access policy or permission boundaries."""
    pass


class MigrationError(DataEngineError):
    """Raised when a schema migration fails preflight or execution."""
    pass


class SecurityViolationError(DataEngineError):
    """Raised when an untrusted identifier or SQL injection pattern is detected."""
    pass
