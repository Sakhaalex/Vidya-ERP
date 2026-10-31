"""
Vidya Data Engine - Safe Parameterized Query Builder & Identifier Guard
Guarantees SQL injection safety by:
1. Strict schema identifier validation against safe regex & schema allow-list.
2. Complete parameterization of all filter values, insertions, and updates.
3. Zero string concatenation of raw user input into query templates.
"""
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.core_engine.exceptions import SecurityViolationError, ValidationError


IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


class IdentifierGuard:
    """Enforces strict identifier rules to prevent SQL injection through identifiers."""

    @staticmethod
    def validate(identifier: str, allowed: Optional[Set[str]] = None) -> str:
        if not identifier or not isinstance(identifier, str):
            raise SecurityViolationError(f"Identifier must be a non-empty string: got {type(identifier)}")
        if not IDENTIFIER_PATTERN.match(identifier):
            raise SecurityViolationError(
                f"Invalid SQL identifier '{identifier}'. Identifiers must be alphanumeric/underscore only."
            )
        if allowed is not None and identifier not in allowed:
            raise SecurityViolationError(
                f"Identifier '{identifier}' is not in the allowed schema list: {sorted(list(allowed))}"
            )
        return identifier

    @staticmethod
    def quote(identifier: str, dialect: str = "standard") -> str:
        """Safely quotes an already-validated identifier."""
        clean = IdentifierGuard.validate(identifier)
        return f'"{clean}"'


class FilterOp(str, Enum):
    EQ = "="
    NEQ = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"
    ILIKE = "ILIKE"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    BETWEEN = "BETWEEN"


class SortDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"


@dataclass(frozen=True)
class SortCriteria:
    column: str
    direction: SortDirection = SortDirection.ASC


@dataclass
class FilterCondition:
    column: str
    operator: FilterOp
    value: Any = None
    second_value: Any = None  # Used for BETWEEN


@dataclass
class QueryPlan:
    """Represents a generated parameterized SQL plan."""
    sql: str
    parameters: Tuple[Any, ...]


class QueryBuilder:
    """Builds parameterized queries for target dialect."""

    def __init__(self, dialect: str = "sqlite"):
        """dialect: 'sqlite' uses '?', 'postgresql' uses '%s'."""
        self.dialect = dialect.lower()
        self.placeholder = "?" if self.dialect == "sqlite" else "%s"

    def build_select(
        self,
        table: str,
        columns: Optional[List[str]] = None,
        filters: Optional[List[FilterCondition]] = None,
        sort: Optional[List[SortCriteria]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        allowed_columns: Optional[Set[str]] = None,
    ) -> QueryPlan:
        safe_table = IdentifierGuard.quote(table)

        if columns:
            safe_cols = ", ".join(
                IdentifierGuard.quote(c) for c in columns
            )
        else:
            safe_cols = "*"

        sql = f"SELECT {safe_cols} FROM {safe_table}"
        params: List[Any] = []

        if filters:
            where_clauses, where_params = self._build_where(filters, allowed_columns)
            if where_clauses:
                sql += f" WHERE {' AND '.join(where_clauses)}"
                params.extend(where_params)

        if sort:
            order_clauses = []
            for s in sort:
                IdentifierGuard.validate(s.column, allowed_columns)
                safe_col = IdentifierGuard.quote(s.column)
                order_clauses.append(f"{safe_col} {s.direction.value}")
            sql += f" ORDER BY {', '.join(order_clauses)}"

        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise ValidationError("Limit must be a non-negative integer")
            sql += f" LIMIT {limit}"

        if offset is not None:
            if not isinstance(offset, int) or offset < 0:
                raise ValidationError("Offset must be a non-negative integer")
            sql += f" OFFSET {offset}"

        return QueryPlan(sql=sql, parameters=tuple(params))

    def build_count(
        self,
        table: str,
        filters: Optional[List[FilterCondition]] = None,
        allowed_columns: Optional[Set[str]] = None,
    ) -> QueryPlan:
        safe_table = IdentifierGuard.quote(table)
        sql = f"SELECT COUNT(*) AS total_count FROM {safe_table}"
        params: List[Any] = []

        if filters:
            where_clauses, where_params = self._build_where(filters, allowed_columns)
            if where_clauses:
                sql += f" WHERE {' AND '.join(where_clauses)}"
                params.extend(where_params)

        return QueryPlan(sql=sql, parameters=tuple(params))

    def build_insert(
        self,
        table: str,
        values: Dict[str, Any],
        returning_col: Optional[str] = None,
        allowed_columns: Optional[Set[str]] = None,
    ) -> QueryPlan:
        if not values:
            raise ValidationError("Cannot build insert with empty values dictionary")

        safe_table = IdentifierGuard.quote(table)
        cols: List[str] = []
        placeholders: List[str] = []
        params: List[Any] = []

        for col, val in values.items():
            IdentifierGuard.validate(col, allowed_columns)
            cols.append(IdentifierGuard.quote(col))
            placeholders.append(self.placeholder)
            params.append(val)

        sql = f"INSERT INTO {safe_table} ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
        if returning_col:
            IdentifierGuard.validate(returning_col, allowed_columns)
            sql += f" RETURNING {IdentifierGuard.quote(returning_col)}"

        return QueryPlan(sql=sql, parameters=tuple(params))

    def build_update(
        self,
        table: str,
        changes: Dict[str, Any],
        pk_column: str,
        pk_value: Any,
        returning_col: Optional[str] = None,
        allowed_columns: Optional[Set[str]] = None,
    ) -> QueryPlan:
        if not changes:
            raise ValidationError("Cannot build update with empty changes dictionary")

        safe_table = IdentifierGuard.quote(table)
        IdentifierGuard.validate(pk_column, allowed_columns)
        safe_pk = IdentifierGuard.quote(pk_column)

        set_clauses: List[str] = []
        params: List[Any] = []

        for col, val in changes.items():
            IdentifierGuard.validate(col, allowed_columns)
            set_clauses.append(f"{IdentifierGuard.quote(col)} = {self.placeholder}")
            params.append(val)

        params.append(pk_value)
        sql = f"UPDATE {safe_table} SET {', '.join(set_clauses)} WHERE {safe_pk} = {self.placeholder}"

        if returning_col:
            IdentifierGuard.validate(returning_col, allowed_columns)
            sql += f" RETURNING {IdentifierGuard.quote(returning_col)}"

        return QueryPlan(sql=sql, parameters=tuple(params))

    def build_delete(
        self,
        table: str,
        pk_column: str,
        pk_value: Any,
        allowed_columns: Optional[Set[str]] = None,
    ) -> QueryPlan:
        safe_table = IdentifierGuard.quote(table)
        IdentifierGuard.validate(pk_column, allowed_columns)
        safe_pk = IdentifierGuard.quote(pk_column)
        sql = f"DELETE FROM {safe_table} WHERE {safe_pk} = {self.placeholder}"
        return QueryPlan(sql=sql, parameters=(pk_value,))

    def _build_where(
        self,
        filters: List[FilterCondition],
        allowed_columns: Optional[Set[str]] = None,
    ) -> Tuple[List[str], List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        for f in filters:
            IdentifierGuard.validate(f.column, allowed_columns)
            safe_col = IdentifierGuard.quote(f.column)

            if f.operator == FilterOp.IS_NULL:
                clauses.append(f"{safe_col} IS NULL")
            elif f.operator == FilterOp.IS_NOT_NULL:
                clauses.append(f"{safe_col} IS NOT NULL")
            elif f.operator in (FilterOp.IN, FilterOp.NOT_IN):
                if not isinstance(f.value, (list, tuple, set)) or len(f.value) == 0:
                    raise ValidationError(f"Filter {f.operator.value} requires a non-empty sequence")
                in_placeholders = ", ".join(self.placeholder for _ in f.value)
                clauses.append(f"{safe_col} {f.operator.value} ({in_placeholders})")
                params.extend(f.value)
            elif f.operator == FilterOp.BETWEEN:
                clauses.append(f"{safe_col} BETWEEN {self.placeholder} AND {self.placeholder}")
                params.append(f.value)
                params.append(f.second_value)
            elif f.operator == FilterOp.ILIKE:
                if self.dialect == "postgresql":
                    clauses.append(f"{safe_col} ILIKE {self.placeholder}")
                    params.append(f.value)
                else:
                    # SQLite: LOWER(col) LIKE LOWER(?)
                    clauses.append(f"LOWER({safe_col}) LIKE LOWER({self.placeholder})")
                    params.append(f.value)
            else:
                clauses.append(f"{safe_col} {f.operator.value} {self.placeholder}")
                params.append(f.value)

        return clauses, params
