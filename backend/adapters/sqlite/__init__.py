"""
Vidya SQLite Adapter Package
"""
from backend.adapters.sqlite.adapter import SQLiteAdapter
from backend.adapters.sqlite.dialect import SQLiteDialect

__all__ = ["SQLiteAdapter", "SQLiteDialect"]
