"""
Vidya Data Engine - Engine Capabilities
Explicitly reports runtime backend capabilities to prevent false assumptions.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class EngineCapabilities:
    """Declared capabilities of a specific database adapter."""
    engine_name: str
    engine_version: str
    supports_returning: bool
    supports_savepoints: bool
    supports_case_insensitive_like: bool
    supports_json_type: bool
    supports_concurrent_writers: bool
    isolation_levels: List[str] = field(default_factory=list)
    supports_full_text_search: bool = False
    supports_ddl_transactions: bool = True
    storage_type: str = "file"  # "file", "network_service", or "cloud"

    def to_dict(self) -> dict:
        return {
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "supports_returning": self.supports_returning,
            "supports_savepoints": self.supports_savepoints,
            "supports_case_insensitive_like": self.supports_case_insensitive_like,
            "supports_json_type": self.supports_json_type,
            "supports_concurrent_writers": self.supports_concurrent_writers,
            "isolation_levels": list(self.isolation_levels),
            "supports_full_text_search": self.supports_full_text_search,
            "supports_ddl_transactions": self.supports_ddl_transactions,
            "storage_type": self.storage_type,
        }
