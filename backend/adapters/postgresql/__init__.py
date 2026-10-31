"""
Vidya PostgreSQL Adapter Package
"""
from backend.adapters.postgresql.adapter import PostgreSQLAdapter
from backend.adapters.postgresql.dialect import PostgreSQLDialect

__all__ = ["PostgreSQLAdapter", "PostgreSQLDialect"]
