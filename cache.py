import json
import os
import sqlite3
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional


def default_cache_path() -> str:
    base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_CACHE_HOME")
    if not base:
        base = str(Path.home() / ".cache")
    return str(Path(base) / "vika_mcp" / "catalog.sqlite3")


class CatalogCache:
    def __init__(self, db_path: Optional[str] = None, ttl_hours: int = 24, enabled: bool = True) -> None:
        self.enabled = enabled
        self.db_path = db_path or default_cache_path()
        self.ttl_seconds = max(1, int(ttl_hours or 24)) * 3600
        self._ready = False
        self._memory_conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        self._ensure_ready()
        if self.db_path == ":memory:":
            return self._connect_raw()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_raw(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_ready(self) -> None:
        if not self.enabled or self._ready:
            return
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._ready = True

    def _init_db(self) -> None:
        with self._connect_raw() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_items (
                    namespace TEXT NOT NULL,
                    space_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    name TEXT,
                    path TEXT,
                    parent_id TEXT,
                    dst_id TEXT,
                    data_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (namespace, item_type, item_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_space_type ON catalog_items(namespace, space_id, item_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_name ON catalog_items(namespace, name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_dst ON catalog_items(namespace, dst_id)")

    def _row_to_item(self, row: sqlite3.Row) -> Dict[str, Any]:
        data = json.loads(row["data_json"])
        return {
            "type": row["item_type"],
            "id": row["item_id"],
            "name": row["name"],
            "path": row["path"],
            "space_id": row["space_id"],
            "parent_id": row["parent_id"],
            "dst_id": row["dst_id"],
            "updated_at": row["updated_at"],
            "data": data,
        }

    def is_fresh(self, updated_at: Optional[float]) -> bool:
        return bool(updated_at and (time.time() - updated_at) <= self.ttl_seconds)

    def upsert_items(self, namespace: str, items: List[Dict[str, Any]]) -> int:
        if not self.enabled or not items:
            return 0
        now = time.time()
        with self._connect() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO catalog_items
                    (namespace, space_id, item_type, item_id, name, path, parent_id, dst_id, data_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        namespace,
                        item.get("space_id") or "",
                        item["type"],
                        item["id"],
                        item.get("name"),
                        item.get("path"),
                        item.get("parent_id"),
                        item.get("dst_id"),
                        json.dumps(item.get("data") or {}, ensure_ascii=False),
                        now,
                    ),
                )
        return len(items)

    def replace_items(self, namespace: str, space_id: str, item_type: str, items: List[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM catalog_items WHERE namespace = ? AND space_id = ? AND item_type = ?",
                (namespace, space_id or "", item_type),
            )
        return self.upsert_items(namespace, items)

    def replace_schema_items(self, namespace: str, datasheet_id: str, items: List[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM catalog_items WHERE namespace = ? AND dst_id = ? AND item_type IN ('field', 'view')",
                (namespace, datasheet_id),
            )
        return self.upsert_items(namespace, items)

    def clear(self, namespace: str, space_id: Optional[str] = None) -> int:
        if not self.enabled:
            return 0
        with self._connect() as conn:
            if space_id:
                cur = conn.execute("DELETE FROM catalog_items WHERE namespace = ? AND space_id = ?", (namespace, space_id))
            else:
                cur = conn.execute("DELETE FROM catalog_items WHERE namespace = ?", (namespace,))
            return cur.rowcount or 0

    def list_items(
        self,
        namespace: str,
        item_type: Optional[str] = None,
        space_id: Optional[str] = None,
        max_age_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        query = "SELECT * FROM catalog_items WHERE namespace = ?"
        params: List[Any] = [namespace]
        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)
        if space_id:
            query += " AND space_id = ?"
            params.append(space_id)
        if max_age_seconds is not None:
            query += " AND updated_at >= ?"
            params.append(time.time() - max_age_seconds)
        query += " ORDER BY path, name"
        with self._connect() as conn:
            return [self._row_to_item(row) for row in conn.execute(query, params)]

    def get_item(self, namespace: str, item_type: str, item_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM catalog_items WHERE namespace = ? AND item_type = ? AND item_id = ?",
                (namespace, item_type, item_id),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def get_schema(self, namespace: str, datasheet_id: str, max_age_seconds: Optional[int] = None) -> Dict[str, Any]:
        fields = self.list_items(namespace, "field", max_age_seconds=max_age_seconds)
        views = self.list_items(namespace, "view", max_age_seconds=max_age_seconds)
        return {
            "fields": [item["data"] for item in fields if item.get("dst_id") == datasheet_id],
            "views": [item["data"] for item in views if item.get("dst_id") == datasheet_id],
        }

    def search(
        self,
        namespace: str,
        query: str,
        space_id: Optional[str] = None,
        node_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        query_norm = (query or "").strip().lower()
        items = self.list_items(namespace, "datasheet", space_id=space_id) + self.list_items(namespace, "node", space_id=space_id)
        results: List[Dict[str, Any]] = []
        seen = set()
        for item in items:
            item_id = item["id"]
            if item_id in seen:
                continue
            seen.add(item_id)
            data = item.get("data") or {}
            if node_type and data.get("type") != node_type and item.get("type") != node_type:
                continue
            name = str(item.get("name") or "")
            path = str(item.get("path") or "")
            haystack = f"{name} {path} {item_id} {item.get('dst_id') or ''}".lower()
            if not query_norm:
                score = 0.5
            elif query_norm == name.lower() or query_norm == item_id.lower() or query_norm == str(item.get("dst_id") or "").lower():
                score = 1.0
            elif query_norm in haystack:
                score = 0.82
            else:
                score = max(
                    SequenceMatcher(None, query_norm, name.lower()).ratio(),
                    SequenceMatcher(None, query_norm, path.lower()).ratio(),
                )
                if score < 0.45:
                    continue
            result = dict(item)
            result["score"] = round(float(score), 4)
            results.append(result)
        results.sort(key=lambda item: (-item["score"], item.get("path") or "", item.get("name") or ""))
        return results[: max(1, int(limit or 20))]

    def status(self, namespace: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "db_path": self.db_path, "items": 0, "oldest_updated_at": None, "newest_updated_at": None}
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS count, MIN(updated_at) AS oldest, MAX(updated_at) AS newest FROM catalog_items WHERE namespace = ?",
                    (namespace,),
                ).fetchone()
        except Exception as exc:
            return {
                "enabled": False,
                "db_path": self.db_path,
                "items": 0,
                "oldest_updated_at": None,
                "newest_updated_at": None,
                "error": str(exc),
            }
        return {
            "enabled": True,
            "db_path": self.db_path,
            "items": int(row["count"] or 0),
            "oldest_updated_at": row["oldest"],
            "newest_updated_at": row["newest"],
            "fresh": self.is_fresh(row["newest"]),
            "ttl_seconds": self.ttl_seconds,
        }


__all__ = ["CatalogCache", "default_cache_path"]
