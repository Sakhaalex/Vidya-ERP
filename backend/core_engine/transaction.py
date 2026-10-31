"""
Vidya Data Engine - Transaction Context & Management
Provides clean atomic units of work, nested savepoint handling,
and commit/rollback hooks without exposing driver connection objects.
"""
from dataclasses import dataclass, field
from enum import Enum
import threading
from typing import Any, Callable, List, Optional
import uuid

from backend.core_engine.exceptions import ConflictError, DataEngineError


class IsolationLevel(str, Enum):
    DEFERRED = "DEFERRED"           # SQLite default
    IMMEDIATE = "IMMEDIATE"         # SQLite write-safe
    EXCLUSIVE = "EXCLUSIVE"         # SQLite full lock
    READ_COMMITTED = "READ COMMITTED"     # PostgreSQL default
    REPEATABLE_READ = "REPEATABLE READ"   # PostgreSQL strict read
    SERIALIZABLE = "SERIALIZABLE"         # Full serializability


@dataclass
class TransactionContext:
    """Encapsulates an active transaction session."""
    tx_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    isolation_level: Optional[IsolationLevel] = None
    read_only: bool = False
    active: bool = True
    savepoints: List[str] = field(default_factory=list)
    raw_connection: Any = None
    _on_commit_callbacks: List[Callable[[], None]] = field(default_factory=list)
    _on_rollback_callbacks: List[Callable[[], None]] = field(default_factory=list)

    def add_commit_callback(self, cb: Callable[[], None]) -> None:
        """Register a callback to run after successful transaction commit."""
        self._on_commit_callbacks.append(cb)

    def add_rollback_callback(self, cb: Callable[[], None]) -> None:
        """Register a callback to run after transaction rollback."""
        self._on_rollback_callbacks.append(cb)

    def trigger_commit(self) -> None:
        self.active = False
        for cb in self._on_commit_callbacks:
            try:
                cb()
            except Exception:
                pass

    def trigger_rollback(self) -> None:
        self.active = False
        for cb in self._on_rollback_callbacks:
            try:
                cb()
            except Exception:
                pass

    def push_savepoint(self, name: str) -> None:
        self.savepoints.append(name)

    def pop_savepoint(self) -> Optional[str]:
        if self.savepoints:
            return self.savepoints.pop()
        return None
