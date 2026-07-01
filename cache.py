import json
import math
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional


CATALOG_READINESS_ERROR_CODES = {
    "empty": "catalog_not_ready",
    "stale": "catalog_stale",
    "refreshing": "catalog_refreshing",
    "refresh_abandoned": "catalog_refresh_abandoned",
    "failed": "catalog_refresh_failed",
    "disabled": "catalog_disabled",
}

CATALOG_READINESS_MESSAGES = {
    "empty": "The workbench catalog is not ready for cache-only discovery.",
    "stale": "The cached workbench catalog is stale and cannot be used for cache-only discovery.",
    "refreshing": "The workbench catalog is currently refreshing and cannot be used for cache-only discovery.",
    "refresh_abandoned": "The last catalog refresh was abandoned and the catalog cannot be trusted for cache-only discovery.",
    "failed": "The last catalog refresh failed and the catalog cannot be trusted for cache-only discovery.",
    "disabled": "Catalog cache is disabled and cannot be used for cache-only discovery.",
}


@dataclass(frozen=True)
class CatalogSelector:
    namespace: str
    item_types: Optional[List[str]] = None
    space_id: Optional[str] = None
    dst_id: Optional[str] = None
    readiness_type: str = "selector"


def catalog_status_value(catalog_status: Dict[str, Any]) -> str:
    candidates = [
        catalog_status.get("readiness_status"),
        catalog_status.get("discovery_status"),
        catalog_status.get("selector_status"),
        catalog_status.get("catalog_status"),
    ]
    for value in candidates:
        if value and str(value) != "ready":
            return str(value)
    for value in candidates:
        if value:
            return str(value)
    return "empty"


def catalog_readiness_error(catalog_status: Dict[str, Any], space_id: Optional[str] = None) -> Dict[str, Any]:
    status = catalog_status_value(catalog_status)
    return {
        "code": CATALOG_READINESS_ERROR_CODES.get(status, "catalog_not_ready"),
        "message": CATALOG_READINESS_MESSAGES.get(status, "The workbench catalog is not ready for cache-only discovery."),
        "details": {
            "space_id": space_id,
            "catalog_status": catalog_status,
        },
    }


def default_cache_path() -> str:
    base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_CACHE_HOME")
    if not base:
        base = str(Path.home() / ".cache")
    return str(Path(base) / "vika_mcp" / "catalog.sqlite3")


class CatalogCache:
    def __init__(
        self,
        db_path: Optional[str] = None,
        ttl_hours: int = 24,
        enabled: bool = True,
        refresh_timeout_seconds: Optional[int] = None,
    ) -> None:
        self.enabled = enabled
        self.db_path = db_path or default_cache_path()
        self.ttl_seconds = max(1, int(ttl_hours or 24)) * 3600
        if refresh_timeout_seconds is None:
            self.refresh_timeout_seconds = max(60, min(self.ttl_seconds, 6 * 3600))
        else:
            self.refresh_timeout_seconds = max(1, int(refresh_timeout_seconds))
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
            existing_state = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'catalog_refresh_state'"
            ).fetchone()
            if existing_state:
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(catalog_refresh_state)")}
                if "space_id" not in columns:
                    conn.execute("DROP TABLE catalog_refresh_state")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_refresh_state (
                    namespace TEXT NOT NULL,
                    space_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    generation_id TEXT,
                    started_at REAL,
                    finished_at REAL,
                    duration_seconds REAL,
                    error TEXT,
                    counts_json TEXT NOT NULL,
                    PRIMARY KEY (namespace, space_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_refresh_space ON catalog_refresh_state(namespace, space_id)")

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
        parsed = self._parse_timestamp(updated_at)
        return bool(parsed and parsed > 0 and (time.time() - parsed) <= self.ttl_seconds)

    def _parse_timestamp(self, value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    def _state_space_key(self, space_id: Optional[str]) -> str:
        return space_id or ""

    def _fetch_refresh_state(self, conn: sqlite3.Connection, namespace: str, space_id: Optional[str]) -> Optional[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM catalog_refresh_state WHERE namespace = ? AND space_id = ?",
            (namespace, self._state_space_key(space_id)),
        ).fetchone()

    def _list_scoped_refresh_space_ids(self, namespace: str) -> List[str]:
        if not self.enabled:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT space_id FROM catalog_refresh_state WHERE namespace = ? AND space_id != ''",
                (namespace,),
            ).fetchall()
        return sorted({str(row["space_id"]) for row in rows if row["space_id"]})

    def _item_freshness(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        item_count = len(items)
        updated_values: List[float] = []
        all_rows_fresh = bool(item_count)
        for item in items:
            updated_at = self._parse_timestamp(item.get("updated_at"))
            if updated_at is None:
                all_rows_fresh = False
                continue
            updated_values.append(updated_at)
            if updated_at <= 0 or not self.is_fresh(updated_at):
                all_rows_fresh = False

        oldest = min(updated_values) if updated_values else None
        newest = max(updated_values) if updated_values else None
        counts: Dict[str, int] = {}
        for item in items:
            item_type = str(item.get("type") or "")
            counts[item_type] = counts.get(item_type, 0) + 1

        return {
            "items": item_count,
            "counts": counts,
            "oldest_updated_at": oldest,
            "newest_updated_at": newest,
            "fresh": bool(item_count and all_rows_fresh),
        }

    def _item_freshness_from_index_rows(
        self,
        conn: sqlite3.Connection,
        namespace: str,
        space_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        filters = "WHERE namespace = ?"
        params: List[Any] = [namespace]
        if space_id:
            filters += " AND space_id = ?"
            params.append(space_id)

        count_rows = conn.execute(
            f"SELECT item_type, COUNT(*) AS count FROM catalog_items {filters} GROUP BY item_type",
            params,
        ).fetchall()
        counts = {str(row["item_type"]): int(row["count"] or 0) for row in count_rows}
        cutoff = time.time() - self.ttl_seconds
        finite_limit = 1.0e308
        freshness_row = conn.execute(
            f"""
            WITH scoped AS (
                SELECT updated_at FROM catalog_items {filters}
            ),
            typed AS (
                SELECT
                    CASE
                        WHEN typeof(updated_at) IN ('integer', 'real') THEN CAST(updated_at AS REAL)
                        WHEN typeof(updated_at) = 'text'
                            AND trim(updated_at) != ''
                            AND trim(updated_at) GLOB '*[0-9]*'
                            AND trim(updated_at) NOT GLOB '*[^0-9eE+.-]*'
                        THEN CAST(updated_at AS REAL)
                        ELSE NULL
                    END AS raw_updated_at
                FROM scoped
            ),
            normalized AS (
                SELECT
                    CASE
                        WHEN raw_updated_at > ? AND raw_updated_at < ? THEN raw_updated_at
                        ELSE NULL
                    END AS updated_at_value
                FROM typed
            )
            SELECT
                COUNT(*) AS item_count,
                MIN(updated_at_value) AS oldest_updated_at,
                MAX(updated_at_value) AS newest_updated_at,
                SUM(CASE
                    WHEN updated_at_value IS NULL OR updated_at_value <= 0 OR updated_at_value < ?
                    THEN 1
                    ELSE 0
                END) AS stale_count
            FROM normalized
            """,
            [*params, -finite_limit, finite_limit, cutoff],
        ).fetchone()
        item_count = int(freshness_row["item_count"] or 0) if freshness_row else 0
        stale_count = int(freshness_row["stale_count"] or 0) if freshness_row else 0
        return {
            "items": item_count,
            "counts": counts,
            "oldest_updated_at": freshness_row["oldest_updated_at"] if freshness_row else None,
            "newest_updated_at": freshness_row["newest_updated_at"] if freshness_row else None,
            "fresh": bool(item_count and stale_count == 0),
        }

    def _refresh_state_info(
        self,
        namespace: str,
        refresh_state: Optional[sqlite3.Row],
        space_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        state_status = refresh_state["status"] if refresh_state else None
        last_error = refresh_state["error"] if refresh_state else None
        last_finished_at = refresh_state["finished_at"] if refresh_state else None
        last_duration = refresh_state["duration_seconds"] if refresh_state else None
        if state_status == "refreshing":
            now = time.time()
            started_at = self._parse_timestamp(refresh_state["started_at"]) if refresh_state else None
            started_at = started_at or 0.0
            if now - started_at > self.refresh_timeout_seconds:
                state_status = "refresh_abandoned"
                last_finished_at = now
                last_duration = max(0.0, now - started_at)
                last_error = f"catalog refresh abandoned after {self.refresh_timeout_seconds} seconds without completion"
                try:
                    with self._connect() as conn:
                        conn.execute(
                            """
                            UPDATE catalog_refresh_state
                            SET status = ?, finished_at = ?, duration_seconds = ?, error = ?
                            WHERE namespace = ? AND space_id = ?
                            """,
                            (
                                state_status,
                                last_finished_at,
                                last_duration,
                                last_error,
                                namespace,
                                self._state_space_key(space_id),
                            ),
                        )
                except Exception:
                    pass

        generation_id = refresh_state["generation_id"] if refresh_state and refresh_state["generation_id"] else None
        refresh_counts: Dict[str, Any] = {}
        if refresh_state and refresh_state["counts_json"]:
            try:
                refresh_counts = json.loads(refresh_state["counts_json"])
            except Exception:
                refresh_counts = {}

        return {
            "state_status": state_status,
            "last_error": last_error,
            "last_finished_at": last_finished_at,
            "last_duration": last_duration,
            "generation_id": generation_id,
            "refresh_counts": refresh_counts,
            "last_refresh_started_at": refresh_state["started_at"] if refresh_state else None,
        }

    def _status_from_items_and_state(self, item_count: int, fresh: bool, state_status: Optional[str]) -> str:
        if state_status == "refreshing":
            return "refreshing"
        if state_status == "refresh_abandoned":
            return "refresh_abandoned"
        if state_status == "failed":
            return "failed"
        if item_count == 0:
            return "empty"
        if fresh:
            return "ready"
        return "stale"

    def _status_report_from_items(
        self,
        namespace: str,
        items: List[Dict[str, Any]],
        space_id: Optional[str] = None,
        item_types: Optional[List[str]] = None,
        selector: Optional[Dict[str, Any]] = None,
        refresh_state: Optional[sqlite3.Row] = None,
    ) -> Dict[str, Any]:
        freshness = self._item_freshness(items)
        return self._status_report_from_freshness(
            namespace,
            freshness,
            space_id=space_id,
            item_types=item_types,
            selector=selector,
            refresh_state=refresh_state,
        )

    def _status_report_from_freshness(
        self,
        namespace: str,
        freshness: Dict[str, Any],
        space_id: Optional[str] = None,
        item_types: Optional[List[str]] = None,
        selector: Optional[Dict[str, Any]] = None,
        refresh_state: Optional[sqlite3.Row] = None,
    ) -> Dict[str, Any]:
        state = self._refresh_state_info(namespace, refresh_state, space_id=space_id)
        catalog_status = self._status_from_items_and_state(
            int(freshness["items"]),
            bool(freshness["fresh"]),
            state["state_status"],
        )
        generation_id = state["generation_id"]
        if not generation_id and freshness["items"]:
            generation_id = f"{int(freshness['newest_updated_at'] or 0)}:{freshness['items']}"

        result = {
            "enabled": self.enabled,
            "db_path": self.db_path,
            "space_id": space_id,
            "items": freshness["items"],
            "counts": freshness["counts"],
            "oldest_updated_at": freshness["oldest_updated_at"],
            "newest_updated_at": freshness["newest_updated_at"],
            "fresh": freshness["fresh"],
            "catalog_status": catalog_status,
            "generation_id": generation_id,
            "ttl_seconds": self.ttl_seconds,
            "last_refresh_started_at": state["last_refresh_started_at"],
            "last_refresh_finished_at": state["last_finished_at"],
            "last_refresh_duration_seconds": state["last_duration"],
            "last_refresh_error": state["last_error"],
            "last_refresh_counts": state["refresh_counts"],
        }
        if selector is not None or item_types is not None:
            result["selector"] = selector or {
                "namespace": namespace,
                "space_id": space_id,
                "item_types": item_types or [],
            }
        return result

    def _catalog_health_from_items(
        self,
        namespace: str,
        items: List[Dict[str, Any]],
        space_id: Optional[str] = None,
        refresh_state: Optional[sqlite3.Row] = None,
    ) -> Dict[str, Any]:
        report = self._status_report_from_items(namespace, items, space_id=space_id, refresh_state=refresh_state)
        report["health_status"] = report["catalog_status"]
        report["status_type"] = "health"
        return report

    def _discovery_readiness_from_items(
        self,
        namespace: str,
        items: List[Dict[str, Any]],
        space_id: Optional[str] = None,
        refresh_state: Optional[sqlite3.Row] = None,
    ) -> Dict[str, Any]:
        report = self._status_report_from_items(
            namespace,
            items,
            space_id=space_id,
            item_types=["node", "datasheet"],
            selector={
                "namespace": namespace,
                "space_id": space_id,
                "item_types": ["node", "datasheet"],
                "readiness_type": "discovery",
            },
            refresh_state=refresh_state,
        )
        report["readiness_type"] = "discovery"
        report["readiness_status"] = report["catalog_status"]
        report["discovery_status"] = report["catalog_status"]
        report["ready_for_discovery"] = report["catalog_status"] == "ready"
        return report

    def _selector_readiness_from_items(
        self,
        namespace: str,
        items: List[Dict[str, Any]],
        space_id: Optional[str] = None,
        item_types: Optional[List[str]] = None,
        selector: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        report = self._status_report_from_items(
            namespace,
            items,
            space_id=space_id,
            item_types=item_types,
            selector=selector,
        )
        report["readiness_type"] = "selector"
        report["readiness_status"] = report["catalog_status"]
        report["selector_status"] = report["catalog_status"]
        return report

    def _insert_items_in_conn(
        self,
        conn: sqlite3.Connection,
        namespace: str,
        items: List[Dict[str, Any]],
        updated_at: float,
    ) -> None:
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
                    updated_at,
                ),
            )

    def upsert_items(self, namespace: str, items: List[Dict[str, Any]]) -> int:
        if not self.enabled or not items:
            return 0
        with self._connect() as conn:
            self._insert_items_in_conn(conn, namespace, items, time.time())
        return len(items)

    def replace_items(self, namespace: str, space_id: str, item_type: str, items: List[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM catalog_items WHERE namespace = ? AND space_id = ? AND item_type = ?",
                (namespace, space_id or "", item_type),
            )
            self._insert_items_in_conn(conn, namespace, items, time.time())
        return len(items)

    def replace_discovery_items(self, namespace: str, space_id: str, items: List[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        allowed_types = {"node", "datasheet"}
        for item in items:
            if item.get("type") not in allowed_types:
                raise ValueError(f"Discovery catalog replacement only accepts node/datasheet items: {item.get('type')}")
            if (item.get("space_id") or "") != (space_id or ""):
                raise ValueError("Discovery catalog replacement item space_id does not match target space_id")
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM catalog_items WHERE namespace = ? AND space_id = ? AND item_type IN ('node', 'datasheet')",
                (namespace, space_id or ""),
            )
            self._insert_items_in_conn(conn, namespace, items, time.time())
        return len(items)

    def replace_schema_items(
        self,
        namespace: str,
        datasheet_id: str,
        items: List[Dict[str, Any]],
        item_types: Optional[List[str]] = None,
    ) -> int:
        if not self.enabled:
            return 0
        requested_types = ["field", "view"] if item_types is None else list(dict.fromkeys(item_types))
        requested_set = set(requested_types)
        if not requested_set or requested_set - {"field", "view"}:
            raise ValueError("Schema catalog replacement item_types must be field and/or view")
        for item in items:
            if item.get("type") not in requested_set:
                raise ValueError("Schema catalog replacement item type is outside requested item_types")
            if item.get("dst_id") != datasheet_id:
                raise ValueError("Schema catalog replacement item dst_id does not match target datasheet_id")
        placeholders = ",".join("?" for _ in requested_types)
        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM catalog_items WHERE namespace = ? AND dst_id = ? AND item_type IN ({placeholders})",
                [namespace, datasheet_id, *requested_types],
            )
            self._insert_items_in_conn(conn, namespace, items, time.time())
        return len(items)

    def clear(self, namespace: str, space_id: Optional[str] = None) -> int:
        if not self.enabled:
            return 0
        with self._connect() as conn:
            if space_id:
                cur = conn.execute("DELETE FROM catalog_items WHERE namespace = ? AND space_id = ?", (namespace, space_id))
                conn.execute(
                    "DELETE FROM catalog_refresh_state WHERE namespace = ? AND space_id = ?",
                    (namespace, self._state_space_key(space_id)),
                )
            else:
                cur = conn.execute("DELETE FROM catalog_items WHERE namespace = ?", (namespace,))
                conn.execute("DELETE FROM catalog_refresh_state WHERE namespace = ?", (namespace,))
            return cur.rowcount or 0

    def begin_refresh(self, namespace: str, space_id: Optional[str]) -> None:
        if not self.enabled:
            return
        started_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO catalog_refresh_state
                (namespace, space_id, status, generation_id, started_at, finished_at, duration_seconds, error, counts_json)
                VALUES (?, ?, 'refreshing', ?, ?, NULL, NULL, NULL, ?)
                """,
                (namespace, self._state_space_key(space_id), str(uuid.uuid4()), started_at, json.dumps({}, ensure_ascii=False)),
            )

    def finish_refresh(
        self,
        namespace: str,
        space_id: Optional[str],
        counts: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        finished_at = time.time()
        with self._connect() as conn:
            space_key = self._state_space_key(space_id)
            row = self._fetch_refresh_state(conn, namespace, space_id)
            generation_id = row["generation_id"] if row and row["generation_id"] else str(uuid.uuid4())
            started_at = float(row["started_at"]) if row and row["started_at"] else finished_at
            conn.execute(
                """
                INSERT OR REPLACE INTO catalog_refresh_state
                (namespace, space_id, status, generation_id, started_at, finished_at, duration_seconds, error, counts_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    namespace,
                    space_key,
                    "failed" if error else "ready",
                    generation_id,
                    started_at,
                    finished_at,
                    max(0.0, finished_at - started_at),
                    error,
                    json.dumps(counts or {}, ensure_ascii=False),
                ),
            )

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

    def _list_selector_items(
        self,
        namespace: str,
        item_types: Optional[List[str]] = None,
        space_id: Optional[str] = None,
        dst_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        query = "SELECT * FROM catalog_items WHERE namespace = ?"
        params: List[Any] = [namespace]
        if item_types:
            placeholders = ",".join("?" for _ in item_types)
            query += f" AND item_type IN ({placeholders})"
            params.extend(item_types)
        if space_id:
            query += " AND space_id = ?"
            params.append(space_id)
        if dst_id:
            query += " AND dst_id = ?"
            params.append(dst_id)
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
        max_age_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        query_norm = (query or "").strip().lower()
        items = self.list_items(namespace, "datasheet", space_id=space_id, max_age_seconds=max_age_seconds) + self.list_items(
            namespace,
            "node",
            space_id=space_id,
            max_age_seconds=max_age_seconds,
        )
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

    def _apply_discovery_gate_to_status(self, health: Dict[str, Any], gate: Dict[str, Any]) -> Dict[str, Any]:
        if gate.get("ready"):
            discovery = gate["catalog"]
            discovery_status = catalog_status_value(discovery)
            health["catalog_status"] = discovery_status
            health["ready_for_discovery"] = True
            health["discovery_status"] = discovery_status
            health["discovery_error"] = None
            return health

        error = gate.get("error") or catalog_readiness_error({"catalog_status": "empty"}, health.get("space_id"))
        error_catalog = error.get("details", {}).get("catalog_status", {}) if isinstance(error, dict) else {}
        discovery_status = catalog_status_value(error_catalog if isinstance(error_catalog, dict) else {})
        health["catalog_status"] = discovery_status
        health["ready_for_discovery"] = False
        health["discovery_status"] = discovery_status
        health["discovery_error"] = error
        return health

    def status(self, namespace: str, space_id: Optional[str] = None) -> Dict[str, Any]:
        discovery_selector = CatalogSelector(
            namespace=namespace,
            item_types=["node", "datasheet"],
            space_id=space_id,
            readiness_type="discovery",
        )
        if not self.enabled:
            result = {
                "enabled": False,
                "db_path": self.db_path,
                "space_id": space_id,
                "items": 0,
                "counts": {},
                "oldest_updated_at": None,
                "newest_updated_at": None,
                "fresh": False,
                "catalog_status": "disabled",
                "generation_id": None,
                "ttl_seconds": self.ttl_seconds,
                "last_refresh_started_at": None,
                "last_refresh_finished_at": None,
                "last_refresh_duration_seconds": None,
                "last_refresh_error": None,
                "last_refresh_counts": {},
                "health_status": "disabled",
                "status_type": "health",
                "ready_for_discovery": False,
                "discovery_status": "disabled",
            }
            return self._apply_discovery_gate_to_status(result, self._readiness_gate(discovery_selector, []))
        try:
            with self._connect() as conn:
                state = self._fetch_refresh_state(conn, namespace, space_id)
                health_freshness = self._item_freshness_from_index_rows(conn, namespace, space_id=space_id)
            discovery_items = self._list_selector_items(namespace, ["node", "datasheet"], space_id=space_id)
        except Exception as exc:
            result = {
                "enabled": True,
                "db_path": self.db_path,
                "space_id": space_id,
                "items": 0,
                "counts": {},
                "oldest_updated_at": None,
                "newest_updated_at": None,
                "fresh": False,
                "catalog_status": "failed",
                "generation_id": None,
                "ttl_seconds": self.ttl_seconds,
                "last_refresh_started_at": None,
                "last_refresh_finished_at": None,
                "last_refresh_duration_seconds": None,
                "last_refresh_error": str(exc),
                "last_refresh_counts": {},
                "health_status": "failed",
                "status_type": "health",
                "ready_for_discovery": False,
                "discovery_status": "failed",
                "error": str(exc),
            }
            result["discovery_error"] = catalog_readiness_error(
                {"catalog_status": "failed", "last_refresh_error": str(exc)},
                space_id,
            )
            return result
        health = self._status_report_from_freshness(namespace, health_freshness, space_id=space_id, refresh_state=state)
        health["status_type"] = "health"
        health["health_status"] = health["catalog_status"]
        return self._apply_discovery_gate_to_status(health, self._readiness_gate(discovery_selector, discovery_items))

    def readiness(self, namespace: str, space_id: Optional[str] = None) -> Dict[str, Any]:
        ready_discovery = self.read_ready_discovery(namespace, space_id=space_id)
        if ready_discovery.get("ready"):
            return {"ready": True, "catalog": ready_discovery["catalog"]}
        return {"ready": False, "error": ready_discovery["error"]}

    def _refresh_blocking_status(self, namespace: str, space_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return {"catalog_status": "disabled", "space_id": space_id}
        try:
            with self._connect() as conn:
                state = self._fetch_refresh_state(conn, namespace, space_id)
        except Exception as exc:
            return {"catalog_status": "failed", "space_id": space_id, "last_refresh_error": str(exc)}
        if not state:
            return None
        freshness = {
            "items": 1,
            "counts": {},
            "oldest_updated_at": None,
            "newest_updated_at": None,
            "fresh": True,
        }
        report = self._status_report_from_freshness(namespace, freshness, space_id=space_id, refresh_state=state)
        if report["catalog_status"] in {"refreshing", "refresh_abandoned", "failed"}:
            return report
        return None

    def _selector_payload(self, selector: CatalogSelector) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "namespace": selector.namespace,
            "space_id": selector.space_id,
            "item_types": selector.item_types or [],
            "readiness_type": selector.readiness_type,
        }
        if selector.dst_id:
            payload["dst_id"] = selector.dst_id
        return payload

    def _selector_refresh_space_ids(self, selector: CatalogSelector, items: List[Dict[str, Any]]) -> List[str]:
        if selector.space_id is not None:
            return [selector.space_id]
        spaces = {
            str(item.get("space_id"))
            for item in items
            if item.get("space_id") is not None and str(item.get("space_id"))
        }
        if selector.dst_id is None:
            spaces.update(self._list_scoped_refresh_space_ids(selector.namespace))
        return sorted(spaces)

    def _selector_refresh_error(
        self,
        selector: CatalogSelector,
        items: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        try:
            refresh_space_ids = self._selector_refresh_space_ids(selector, items)
        except Exception as exc:
            return catalog_readiness_error(
                {"catalog_status": "failed", "last_refresh_error": str(exc)},
                selector.space_id,
            )
        for space_id in refresh_space_ids:
            blocking_status = self._refresh_blocking_status(selector.namespace, space_id=space_id)
            if blocking_status is not None:
                return catalog_readiness_error(blocking_status, space_id)
        return None

    def _selector_refresh_state_for_report(self, selector: CatalogSelector) -> Optional[sqlite3.Row]:
        if selector.space_id is None:
            return None
        try:
            with self._connect() as conn:
                return self._fetch_refresh_state(conn, selector.namespace, selector.space_id)
        except Exception:
            return None

    def _readiness_gate(self, selector: CatalogSelector, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.enabled:
            return {"ready": False, "error": catalog_readiness_error({"catalog_status": "disabled"}, selector.space_id)}

        refresh_error = self._selector_refresh_error(selector, items)
        if refresh_error is not None:
            return {"ready": False, "error": refresh_error}

        if selector.readiness_type == "discovery":
            discovery = self._discovery_readiness_from_items(
                selector.namespace,
                items,
                space_id=selector.space_id,
                refresh_state=self._selector_refresh_state_for_report(selector),
            )
            if not discovery.get("ready_for_discovery"):
                return {"ready": False, "error": catalog_readiness_error(discovery, selector.space_id)}
            return {"ready": True, "catalog": discovery}

        selector_status = self._selector_readiness_from_items(
            selector.namespace,
            items,
            space_id=selector.space_id,
            item_types=selector.item_types,
            selector=self._selector_payload(selector),
        )
        if selector_status["selector_status"] != "ready":
            return {"ready": False, "error": catalog_readiness_error(selector_status, selector.space_id)}
        return {"ready": True, "catalog": selector_status}

    def read_ready_discovery(self, namespace: str, space_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.enabled:
            return {"ready": False, "error": catalog_readiness_error({"catalog_status": "disabled"}, space_id)}
        try:
            items = self._list_selector_items(namespace, ["node", "datasheet"], space_id=space_id)
        except Exception as exc:
            return {
                "ready": False,
                "error": catalog_readiness_error(
                    {"catalog_status": "failed", "last_refresh_error": str(exc)},
                    space_id,
                ),
            }
        selector = CatalogSelector(
            namespace=namespace,
            item_types=["node", "datasheet"],
            space_id=space_id,
            readiness_type="discovery",
        )
        readiness = self._readiness_gate(selector, items)
        if not readiness.get("ready"):
            return readiness
        return {"ready": True, "items": items, "catalog": readiness["catalog"]}

    def read_ready_items(
        self,
        namespace: str,
        item_type: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        item_types = [item_type] if item_type else None
        items = self._list_selector_items(namespace, item_types, space_id=space_id)
        readiness = self._readiness_gate(
            CatalogSelector(namespace=namespace, item_types=item_types, space_id=space_id),
            items,
        )
        if not readiness.get("ready"):
            return readiness
        return {
            "ready": True,
            "items": items,
            "catalog": readiness["catalog"],
        }

    def search_ready(
        self,
        namespace: str,
        query: str,
        space_id: Optional[str] = None,
        node_type: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        searchable_items = self._list_selector_items(namespace, ["datasheet", "node"], space_id=space_id)
        readiness = self._readiness_gate(
            CatalogSelector(namespace=namespace, item_types=["datasheet", "node"], space_id=space_id),
            searchable_items,
        )
        if not readiness.get("ready"):
            return readiness
        return {
            "ready": True,
            "matches": self.search(
                namespace,
                query,
                space_id=space_id,
                node_type=node_type,
                limit=limit,
                max_age_seconds=self.ttl_seconds,
            ),
            "catalog": readiness["catalog"],
        }

    def get_ready_item(self, namespace: str, item_type: str, item_id: str) -> Dict[str, Any]:
        item = self.get_item(namespace, item_type, item_id)
        if item is None:
            items = self._list_selector_items(namespace, [item_type])
            readiness = self._readiness_gate(
                CatalogSelector(namespace=namespace, item_types=[item_type]),
                items,
            )
            if not readiness.get("ready"):
                return readiness
            return {"ready": True, "item": None, "catalog": readiness["catalog"]}
        selector = self._ready_item_selector(namespace, item_type, item)
        items = self._list_selector_items(
            namespace,
            [item_type],
            space_id=selector.get("space_id"),
            dst_id=selector.get("dst_id"),
        )
        readiness = self._readiness_gate(
            CatalogSelector(
                namespace=namespace,
                item_types=[item_type],
                space_id=selector.get("space_id"),
                dst_id=selector.get("dst_id"),
            ),
            items,
        )
        if not readiness.get("ready"):
            error = dict(readiness["error"])
            details = dict(error.get("details") or {})
            details.update({"item_type": item_type, "item_id": item_id})
            error["details"] = details
            return {"ready": False, "error": error}
        return {"ready": True, "item": item, "catalog": readiness["catalog"]}

    def _ready_item_selector(self, namespace: str, item_type: str, item: Dict[str, Any]) -> Dict[str, Any]:
        selector: Dict[str, Any] = {
            "namespace": namespace,
            "item_types": [item_type],
        }
        if item_type in {"field", "view"} and item.get("dst_id"):
            selector["dst_id"] = item.get("dst_id")
            return selector
        if item.get("space_id"):
            selector["space_id"] = item.get("space_id")
        return selector


__all__ = ["CatalogCache", "catalog_readiness_error", "catalog_status_value", "default_cache_path"]
