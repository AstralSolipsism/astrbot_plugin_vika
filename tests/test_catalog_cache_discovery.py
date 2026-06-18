from __future__ import annotations

import pytest


def test_catalog_content_readers_use_single_readiness_gate() -> None:
    import inspect

    from vika_mcp.cache import CatalogCache

    gated_methods = [
        CatalogCache.status,
        CatalogCache.read_ready_discovery,
        CatalogCache.read_ready_items,
        CatalogCache.search_ready,
        CatalogCache.get_ready_item,
    ]

    for method in gated_methods:
        assert "_readiness_gate(" in inspect.getsource(method), method.__name__

    cache_source = inspect.getsource(CatalogCache)
    assert "def _selector_ready_result" not in cache_source
    assert cache_source.count("_refresh_blocking_status(") == 2


class _RawNode:
    def __init__(self, node_id: str, name: str, node_type: str, parent_id: str | None = None) -> None:
        self.raw_data = {"id": node_id, "name": name, "type": node_type, "parentId": parent_id}


class _FakeNodes:
    def __init__(
        self,
        *,
        alist_nodes: list[_RawNode] | None = None,
        search_nodes: dict[str, list[_RawNode]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.alist_nodes = alist_nodes or []
        self.search_nodes = search_nodes or {}
        self.errors = errors or {}
        self.searched_types: list[str | None] = []

    async def alist(self):
        if "nodes.alist" in self.errors:
            raise self.errors["nodes.alist"]
        return self.alist_nodes

    async def asearch(self, node_type=None, **kwargs):
        self.searched_types.append(node_type)
        request = f"nodes.asearch:{node_type}"
        if request in self.errors:
            raise self.errors[request]
        return self.search_nodes.get(node_type, [])


class _FakeSpace:
    def __init__(self, nodes: _FakeNodes) -> None:
        self.nodes = nodes


class _RawSchemaItem:
    def __init__(self, raw_data: dict) -> None:
        self.raw_data = raw_data


class _FakeSchemaCollection:
    def __init__(self, items: list[dict], error: Exception | None = None) -> None:
        self.items = [_RawSchemaItem(item) for item in items]
        self.error = error
        self.calls = 0

    async def aall(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.items


class _FakeDatasheet:
    def __init__(
        self,
        *,
        fields: list[dict] | None = None,
        views: list[dict] | None = None,
        fields_error: Exception | None = None,
        views_error: Exception | None = None,
    ) -> None:
        self.fields = _FakeSchemaCollection(fields or [], fields_error)
        self.views = _FakeSchemaCollection(views or [], views_error)


class _FakeVika:
    def __init__(self, nodes: _FakeNodes, datasheets: dict[str, _FakeDatasheet] | None = None) -> None:
        self.nodes = nodes
        self.datasheets = datasheets or {}
        self.closed = False

    def space(self, space_id):
        return _FakeSpace(self.nodes)

    def datasheet(self, datasheet_id, space_id=None):
        return self.datasheets[datasheet_id]

    async def aclose(self):
        self.closed = True


def cache_item_ids(cache, namespace: str, item_type: str) -> set[str]:
    return {item["id"] for item in cache.list_items(namespace, item_type)}


def seed_node(cache, namespace: str, space_id: str = "spc1", node_id: str = "fodRoot") -> None:
    cache.upsert_items(
        namespace,
        [
            {
                "type": "node",
                "id": node_id,
                "space_id": space_id,
                "name": "root",
                "path": "root",
                "data": {"id": node_id, "type": "Folder"},
            }
        ],
    )


def force_stale(cache, namespace: str) -> None:
    with cache._connect() as conn:
        conn.execute("UPDATE catalog_items SET updated_at = 0 WHERE namespace = ?", (namespace,))


def mark_failed(cache, namespace: str, message: str = "boom", space_id: str | None = "spc1") -> None:
    cache.begin_refresh(namespace, space_id)
    cache.finish_refresh(namespace, space_id, {"nodes": 0}, error=message)


def mark_space_stale(cache, namespace: str, space_id: str) -> None:
    with cache._connect() as conn:
        conn.execute(
            "UPDATE catalog_items SET updated_at = 0 WHERE namespace = ? AND space_id = ?",
            (namespace, space_id),
        )


def mark_item_stale(cache, namespace: str, item_type: str, item_id: str) -> None:
    with cache._connect() as conn:
        conn.execute(
            "UPDATE catalog_items SET updated_at = 0 WHERE namespace = ? AND item_type = ? AND item_id = ?",
            (namespace, item_type, item_id),
        )


def set_item_updated_at(cache, namespace: str, item_type: str, item_id: str, updated_at) -> None:
    with cache._connect() as conn:
        conn.execute(
            "UPDATE catalog_items SET updated_at = ? WHERE namespace = ? AND item_type = ? AND item_id = ?",
            (updated_at, namespace, item_type, item_id),
        )


def seed_catalog_item(cache, namespace: str, item_type: str, item_id: str, space_id: str = "spc1") -> None:
    data = {"id": item_id, "type": item_type}
    item = {
        "type": item_type,
        "id": item_id,
        "space_id": space_id,
        "name": item_id,
        "path": item_id,
        "data": data,
    }
    if item_type in {"field", "view"}:
        item["dst_id"] = "dst1"
    if item_type == "datasheet":
        item["dst_id"] = item_id
    cache.upsert_items(namespace, [item])


def test_replace_discovery_items_is_atomic_when_insert_fails() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    namespace = "namespace"
    cache.upsert_items(
        namespace,
        [
            {
                "type": "node",
                "id": "fodOld",
                "space_id": "spc1",
                "name": "old folder",
                "path": "old folder",
                "data": {"id": "fodOld", "type": "Folder"},
            },
            {
                "type": "datasheet",
                "id": "dstOld",
                "space_id": "spc1",
                "name": "old table",
                "path": "old folder/old table",
                "dst_id": "dstOld",
                "data": {"id": "dstOld", "type": "Datasheet"},
            },
        ],
    )

    with pytest.raises(TypeError):
        cache.replace_discovery_items(
            namespace,
            "spc1",
            [
                {
                    "type": "node",
                    "id": "fodNew",
                    "space_id": "spc1",
                    "name": "new folder",
                    "path": "new folder",
                    "data": {"not_json": object()},
                }
            ],
        )

    assert cache.get_item(namespace, "node", "fodOld") is not None
    assert cache.get_item(namespace, "datasheet", "dstOld") is not None
    assert cache.get_item(namespace, "node", "fodNew") is None


def test_replace_schema_items_can_atomically_replace_one_item_type() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    namespace = "namespace"
    cache.replace_schema_items(
        namespace,
        "dst1",
        [
            {
                "type": "field",
                "id": "dst1:fldOld",
                "space_id": "spc1",
                "name": "old field",
                "path": "dst1/old field",
                "dst_id": "dst1",
                "data": {"id": "fldOld", "name": "old field"},
            },
            {
                "type": "view",
                "id": "dst1:viwOld",
                "space_id": "spc1",
                "name": "old view",
                "path": "dst1/old view",
                "dst_id": "dst1",
                "data": {"id": "viwOld", "name": "old view"},
            },
        ],
    )

    cache.replace_schema_items(
        namespace,
        "dst1",
        [
            {
                "type": "field",
                "id": "dst1:fldNew",
                "space_id": "spc1",
                "name": "new field",
                "path": "dst1/new field",
                "dst_id": "dst1",
                "data": {"id": "fldNew", "name": "new field"},
            }
        ],
        item_types=["field"],
    )

    assert cache.get_item(namespace, "field", "dst1:fldOld") is None
    assert cache.get_item(namespace, "field", "dst1:fldNew") is not None
    assert cache.get_item(namespace, "view", "dst1:viwOld") is not None


def test_replace_schema_items_preserves_old_rows_when_selective_insert_fails() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    namespace = "namespace"
    cache.replace_schema_items(
        namespace,
        "dst1",
        [
            {
                "type": "field",
                "id": "dst1:fldOld",
                "space_id": "spc1",
                "name": "old field",
                "path": "dst1/old field",
                "dst_id": "dst1",
                "data": {"id": "fldOld", "name": "old field"},
            },
            {
                "type": "view",
                "id": "dst1:viwOld",
                "space_id": "spc1",
                "name": "old view",
                "path": "dst1/old view",
                "dst_id": "dst1",
                "data": {"id": "viwOld", "name": "old view"},
            },
        ],
    )

    with pytest.raises(TypeError):
        cache.replace_schema_items(
            namespace,
            "dst1",
            [
                {
                    "type": "field",
                    "id": "dst1:fldBad",
                    "space_id": "spc1",
                    "name": "bad field",
                    "path": "dst1/bad field",
                    "dst_id": "dst1",
                    "data": {"not_json": object()},
                }
            ],
            item_types=["field"],
        )

    assert cache.get_item(namespace, "field", "dst1:fldOld") is not None
    assert cache.get_item(namespace, "view", "dst1:viwOld") is not None
    assert cache.get_item(namespace, "field", "dst1:fldBad") is None


def test_replace_schema_items_rejects_empty_item_type_selection() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")

    with pytest.raises(ValueError):
        cache.replace_schema_items("namespace", "dst1", [], item_types=[])


def test_catalog_status_and_readiness_treat_invalid_timestamps_as_stale() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    seed_node(cache, "namespace")
    set_item_updated_at(cache, "namespace", "node", "fodRoot", "not-a-timestamp")

    status = cache.status("namespace", "spc1")
    readiness = cache.readiness("namespace", "spc1")

    assert status["catalog_status"] == "stale"
    assert status["fresh"] is False
    assert status["oldest_updated_at"] is None
    assert status["newest_updated_at"] is None
    assert readiness["ready"] is False
    assert readiness["error"]["code"] == "catalog_stale"


@pytest.mark.parametrize("item_type", ["space", "field", "view"])
def test_catalog_status_does_not_treat_non_discovery_rows_as_discovery_ready(item_type: str) -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    seed_catalog_item(cache, "namespace", item_type, f"{item_type}1")

    status = cache.status("namespace", "spc1")
    readiness = cache.readiness("namespace", "spc1")

    assert status["counts"][item_type] == 1
    assert status["health_status"] == "ready"
    assert status["catalog_status"] == "empty"
    assert status["ready_for_discovery"] is False
    assert status["discovery_status"] == "empty"
    assert status["discovery_error"]["code"] == "catalog_not_ready"
    assert readiness["ready"] is False
    assert readiness["error"]["code"] == "catalog_not_ready"


def test_catalog_status_uses_sql_health_without_deserializing_non_discovery_rows() -> None:
    import time

    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    with cache._connect() as conn:
        conn.execute(
            """
            INSERT INTO catalog_items
            (namespace, space_id, item_type, item_id, name, path, parent_id, dst_id, data_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("namespace", "spc1", "field", "fldBadJson", "bad", "bad", None, "dst1", "{not-json", time.time()),
        )

    status = cache.status("namespace", "spc1")

    assert status["counts"]["field"] == 1
    assert status["health_status"] == "ready"
    assert status["catalog_status"] == "empty"
    assert status["ready_for_discovery"] is False
    assert status["discovery_error"]["code"] == "catalog_not_ready"


def test_catalog_status_reads_only_discovery_selector_items(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    seed_catalog_item(cache, "namespace", "node", "fod1")
    original_list_selector_items = cache._list_selector_items
    selector_item_types: list[list[str] | None] = []

    def tracked_list_selector_items(namespace, item_types=None, space_id=None, dst_id=None):
        selector_item_types.append(item_types)
        if item_types is None:
            raise AssertionError("status must not perform full catalog selector reads")
        return original_list_selector_items(namespace, item_types=item_types, space_id=space_id, dst_id=dst_id)

    monkeypatch.setattr(cache, "_list_selector_items", tracked_list_selector_items)

    status = cache.status("namespace", "spc1")

    assert status["ready_for_discovery"] is True
    assert selector_item_types == [["node", "datasheet"]]


def test_catalog_status_health_uses_sql_aggregate_not_timestamp_row_loop() -> None:
    import inspect

    from vika_mcp.cache import CatalogCache

    source = inspect.getsource(CatalogCache._item_freshness_from_index_rows)

    assert "timestamp_rows" not in source
    assert source.count(".fetchall()") == 1
    assert "SUM(CASE" in source


@pytest.mark.parametrize(
    "state",
    ["empty", "stale", "failed", "refreshing", "refresh_abandoned", "ready", "disabled"],
)
def test_catalog_status_invokes_discovery_gate_for_all_states(monkeypatch, state: str) -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:", refresh_timeout_seconds=1, enabled=state != "disabled")
    if state in {"stale", "failed", "refreshing", "refresh_abandoned", "ready"}:
        seed_node(cache, "namespace")
    if state == "stale":
        force_stale(cache, "namespace")
    if state == "failed":
        mark_failed(cache, "namespace", space_id="spc1")
    if state in {"refreshing", "refresh_abandoned"}:
        cache.begin_refresh("namespace", "spc1")
    if state == "refresh_abandoned":
        with cache._connect() as conn:
            conn.execute(
                "UPDATE catalog_refresh_state SET started_at = 0 WHERE namespace = ? AND space_id = ?",
                ("namespace", "spc1"),
            )

    original_gate = cache._readiness_gate
    calls: list[tuple[str, list[str] | None, str | None]] = []

    def tracked_gate(selector, items):
        calls.append((selector.readiness_type, selector.item_types, selector.space_id))
        return original_gate(selector, items)

    monkeypatch.setattr(cache, "_readiness_gate", tracked_gate)

    status = cache.status("namespace", "spc1")

    assert calls == [("discovery", ["node", "datasheet"], "spc1")]
    assert status["ready_for_discovery"] is (state == "ready")
    assert status["discovery_status"] == ("ready" if state == "ready" else state)


@pytest.mark.parametrize("item_type", ["node", "datasheet"])
def test_catalog_status_marks_discovery_rows_as_discovery_ready(item_type: str) -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    seed_catalog_item(cache, "namespace", item_type, "dst1" if item_type == "datasheet" else "fod1")

    status = cache.status("namespace", "spc1")
    readiness = cache.readiness("namespace", "spc1")

    assert status["health_status"] == "ready"
    assert status["catalog_status"] == "ready"
    assert status["ready_for_discovery"] is True
    assert status["discovery_status"] == "ready"
    assert status["discovery_error"] is None
    assert readiness["ready"] is True


@pytest.mark.asyncio
async def test_client_catalog_status_defaults_to_workbench_space_scope() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", workbench_space_id="spcTarget", cache=cache)
    seed_catalog_item(cache, client.namespace, "node", "fodOther", space_id="spcOther")
    seed_catalog_item(cache, client.namespace, "datasheet", "dstOther", space_id="spcOther")

    default_status = client.catalog_status()
    explicit_other_status = client.catalog_status(space_id="spcOther")
    target_discovery = await client.nodes_list("spcTarget", cache_only=True)

    assert default_status["space_id"] == "spcTarget"
    assert default_status["ready_for_discovery"] is False
    assert default_status["discovery_status"] == "empty"
    assert target_discovery["error"]["code"] == "catalog_not_ready"
    assert explicit_other_status["space_id"] == "spcOther"
    assert explicit_other_status["ready_for_discovery"] is True


@pytest.mark.asyncio
async def test_nodes_list_cache_only_reports_cache_read_failure_without_api_fallback(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)

    def fail_readiness(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cache, "read_ready_discovery", fail_readiness)
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("cache-only failure must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["space_id"] == "spc1"
    assert result["error"]["details"]["catalog_status"]["last_refresh_error"] == "boom"


def test_catalog_search_reports_cache_read_failure_as_catalog_error(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)

    def fail_search(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cache, "search_ready", fail_search)

    result = client.catalog_search("客户", space_id="spc1")

    assert result["source"] == "cache"
    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["space_id"] == "spc1"
    assert result["error"]["details"]["catalog_status"]["last_refresh_error"] == "boom"


def test_catalog_get_reports_cache_read_failure_as_catalog_error(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)

    def fail_get(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cache, "get_ready_item", fail_get)

    result = client.catalog_get("datasheet", "dst1")

    assert result["source"] == "cache"
    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["space_id"] is None
    assert result["error"]["details"]["catalog_status"]["last_refresh_error"] == "boom"


@pytest.mark.asyncio
async def test_refresh_failure_in_other_space_does_not_block_ready_space(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    seed_catalog_item(cache, client.namespace, "node", "fodA", space_id="spcA")
    seed_catalog_item(cache, client.namespace, "datasheet", "dstA", space_id="spcA")
    seed_catalog_item(cache, client.namespace, "node", "fodB", space_id="spcB")
    seed_catalog_item(cache, client.namespace, "datasheet", "dstB", space_id="spcB")
    cache.begin_refresh(client.namespace, "spcB")
    cache.finish_refresh(client.namespace, "spcB", {"nodes": 0}, error="spcB failed")
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("ready cache-only discovery must not open the Vika API"))

    status_a = client.catalog_status(space_id="spcA")
    discovery_a = await client.nodes_list("spcA", cache_only=True)
    status_b = client.catalog_status(space_id="spcB")

    assert status_a["ready_for_discovery"] is True
    assert status_a["discovery_status"] == "ready"
    assert discovery_a["source"] == "cache"
    assert {node["id"] for node in discovery_a["nodes"]} == {"fodA", "dstA"}
    assert status_b["ready_for_discovery"] is False
    assert status_b["discovery_status"] == "failed"


def test_refreshing_and_abandoned_states_are_scoped_to_target_space() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:", refresh_timeout_seconds=1)
    seed_catalog_item(cache, "namespace", "node", "fodA", space_id="spcA")
    seed_catalog_item(cache, "namespace", "datasheet", "dstA", space_id="spcA")
    seed_catalog_item(cache, "namespace", "node", "fodB", space_id="spcB")
    seed_catalog_item(cache, "namespace", "datasheet", "dstB", space_id="spcB")

    cache.begin_refresh("namespace", "spcB")

    assert cache.readiness("namespace", "spcA")["ready"] is True
    assert cache.readiness("namespace", "spcB")["error"]["code"] == "catalog_refreshing"

    with cache._connect() as conn:
        conn.execute(
            "UPDATE catalog_refresh_state SET started_at = 0 WHERE namespace = ? AND space_id = ?",
            ("namespace", "spcB"),
        )

    assert cache.readiness("namespace", "spcA")["ready"] is True
    assert cache.readiness("namespace", "spcB")["error"]["code"] == "catalog_refresh_abandoned"


def test_catalog_clear_space_removes_only_matching_items_and_refresh_state() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    seed_catalog_item(cache, "namespace", "node", "fodA", space_id="spcA")
    seed_catalog_item(cache, "namespace", "datasheet", "dstA", space_id="spcA")
    seed_catalog_item(cache, "namespace", "node", "fodB", space_id="spcB")
    seed_catalog_item(cache, "namespace", "datasheet", "dstB", space_id="spcB")
    cache.begin_refresh("namespace", "spcA")
    cache.finish_refresh("namespace", "spcA", {"nodes": 2})
    cache.begin_refresh("namespace", "spcB")
    cache.finish_refresh("namespace", "spcB", {"nodes": 0}, error="spcB failed")

    cleared = cache.clear("namespace", space_id="spcA")

    assert cleared == 2
    assert cache.status("namespace", space_id="spcA")["discovery_status"] == "empty"
    assert cache.status("namespace", space_id="spcA")["last_refresh_error"] is None
    assert cache.status("namespace", space_id="spcB")["discovery_status"] == "failed"
    assert cache.get_item("namespace", "node", "fodB") is not None


def test_selector_readiness_treats_missing_zero_negative_and_expired_timestamps_as_stale() -> None:
    import time

    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:", ttl_hours=1)
    fresh_status = cache._selector_readiness_from_items(
        "namespace",
        [{"type": "node", "id": "fresh", "updated_at": time.time()}],
        space_id="spc1",
        item_types=["node"],
    )
    assert fresh_status["catalog_status"] == "ready"
    assert fresh_status["selector_status"] == "ready"
    assert fresh_status["fresh"] is True

    stale_inputs = [
        {"type": "node", "id": "missing"},
        {"type": "node", "id": "zero", "updated_at": 0},
        {"type": "node", "id": "negative", "updated_at": -1},
        {"type": "node", "id": "expired", "updated_at": 1},
    ]

    for item in stale_inputs:
        status = cache._selector_readiness_from_items("namespace", [item], space_id="spc1", item_types=["node"])
        assert status["selector_status"] == "stale"
        assert status["fresh"] is False


@pytest.mark.asyncio
async def test_nodes_list_cache_only_empty_cache_does_not_open_api(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("cache-only discovery must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["error"]["code"] == "catalog_not_ready"
    assert result["error"]["details"]["space_id"] == "spc1"


@pytest.mark.asyncio
async def test_nodes_list_cache_only_stale_cache_does_not_open_api(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:", ttl_hours=1)
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "node",
                "id": "fodRoot",
                "space_id": "spc1",
                "name": "root",
                "path": "root",
                "data": {"id": "fodRoot", "type": "Folder"},
            }
        ],
    )
    with cache._connect() as conn:
        conn.execute("UPDATE catalog_items SET updated_at = 0")

    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("stale cache-only discovery must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["error"]["code"] == "catalog_stale"
    assert result["error"]["details"]["space_id"] == "spc1"


@pytest.mark.asyncio
async def test_catalog_refresh_node_loader_indexes_only_folder_and_datasheet_by_default(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        alist_nodes=[
            _RawNode("frm1", "form", "Form", "fodRoot"),
            _RawNode("dsh1", "dashboard", "Dashboard", "fodRoot"),
        ],
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.nodes_list("spc1", use_cache=False, force_refresh=True)

    assert result["source"] == "api"
    assert nodes.searched_types == ["Folder", "Datasheet"]
    assert {item["id"] for item in result["nodes"]} == {"fodRoot", "dst1"}
    assert cache_item_ids(client.cache, client.namespace, "node") == {"fodRoot", "dst1"}
    assert [item["request"] for item in result["refresh_requests"]] == [
        "nodes.alist",
        "nodes.asearch:Folder",
        "nodes.asearch:Datasheet",
    ]
    assert {item["error"] for item in result["refresh_requests"]} == {None}


@pytest.mark.asyncio
async def test_catalog_refresh_without_bounded_space_rejects_without_space_scan(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:"))
    monkeypatch.setattr(client, "spaces_list", lambda *args, **kwargs: pytest.fail("catalog refresh must not list token-wide spaces"))
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("catalog refresh without target must not open Vika API"))

    result = await client.catalog_refresh()

    assert result["error"]["code"] == "catalog_refresh_scope_required"
    assert client.catalog_status()["catalog_status"] == "empty"


@pytest.mark.asyncio
async def test_catalog_refresh_without_cache_rejects_without_api(monkeypatch) -> None:
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(api_token="token", host="https://vika.cn", cache=None)
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("refresh without cache must not open Vika API"))

    result = await client.catalog_refresh(space_id="spc1")

    assert result["error"]["code"] == "catalog_disabled"
    assert "refreshed" not in result
    assert result["cache"]["enabled"] is False


@pytest.mark.asyncio
async def test_catalog_refresh_disabled_cache_rejects_without_api(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:", enabled=False))
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("refresh with disabled cache must not open Vika API"))

    result = await client.catalog_refresh(space_id="spc1")

    assert result["error"]["code"] == "catalog_disabled"
    assert "refreshed" not in result
    assert result["cache"]["enabled"] is False
    assert result["cache"]["discovery_status"] == "disabled"


@pytest.mark.asyncio
async def test_nodes_list_force_refresh_without_cache_rejects_without_api(monkeypatch) -> None:
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(api_token="token", host="https://vika.cn", cache=None)
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("force refresh without cache must not open Vika API"))

    result = await client.nodes_list("spc1", use_cache=False, force_refresh=True)

    assert result["error"]["code"] == "catalog_disabled"


@pytest.mark.asyncio
async def test_nodes_list_force_refresh_disabled_cache_rejects_without_api(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:", enabled=False))
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("force refresh with disabled cache must not open Vika API"))

    result = await client.nodes_list("spc1", use_cache=False, force_refresh=True)

    assert result["error"]["code"] == "catalog_disabled"


@pytest.mark.asyncio
async def test_nodes_list_non_refresh_api_without_cache_still_works(monkeypatch) -> None:
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=None)
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.nodes_list("spc1", use_cache=False, force_refresh=False)

    assert result["source"] == "api"
    assert {item["id"] for item in result["nodes"]} == {"fodRoot", "dst1"}


@pytest.mark.asyncio
async def test_catalog_refresh_explicit_space_does_not_call_spaces_list(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:"))
    monkeypatch.setattr(client, "spaces_list", lambda *args, **kwargs: pytest.fail("explicit-space refresh must not list token-wide spaces"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.catalog_refresh(space_id="spc1")

    assert result["refreshed"] is True
    assert result["space_ids"] == ["spc1"]
    assert result["counts"]["spaces"] == 1
    assert nodes.searched_types == ["Folder", "Datasheet"]


@pytest.mark.asyncio
async def test_nodes_list_force_refresh_returns_error_when_cache_persist_fails(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    class FailingDiscoveryCache(CatalogCache):
        def replace_discovery_items(self, namespace, space_id, items):
            raise RuntimeError("disk full")

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=FailingDiscoveryCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.nodes_list("spc1", use_cache=False, force_refresh=True)

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["space_id"] == "spc1"
    assert result["error"]["details"]["stage"] == "cache_persist"
    assert result["error"]["details"]["error_type"] == "RuntimeError"
    assert "source" not in result


@pytest.mark.asyncio
async def test_catalog_refresh_returns_failed_when_discovery_cache_persist_fails(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    class FailingDiscoveryCache(CatalogCache):
        def replace_discovery_items(self, namespace, space_id, items):
            raise RuntimeError("disk full")

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=FailingDiscoveryCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.catalog_refresh(space_id="spc1")

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["stage"] == "cache_persist"
    assert result["cache"]["ready_for_discovery"] is False


@pytest.mark.asyncio
async def test_catalog_refresh_reports_failed_state_write_error(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    class FailingDiscoveryAndStateCache(CatalogCache):
        def replace_discovery_items(self, namespace, space_id, items):
            raise RuntimeError("disk full")

        def finish_refresh(self, namespace, space_id, counts, error=None):
            raise RuntimeError("state locked")

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=FailingDiscoveryAndStateCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.catalog_refresh(space_id="spc1")

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["stage"] == "cache_persist"
    assert result["error"]["details"]["failed_state_error"]["type"] == "RuntimeError"
    assert result["error"]["details"]["failed_state_error"]["message"] == "state locked"


@pytest.mark.asyncio
async def test_catalog_refresh_success_state_write_failure_is_not_reported_as_refreshed(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    class FailingReadyStateCache(CatalogCache):
        def finish_refresh(self, namespace, space_id, counts, error=None):
            if error is None:
                raise RuntimeError("ready state locked")
            return super().finish_refresh(namespace, space_id, counts, error=error)

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=FailingReadyStateCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.catalog_refresh(space_id="spc1")

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["stage"] == "refresh_state_finish"
    assert "refreshed" not in result
    assert result["cache"]["catalog_status"] == "failed"


@pytest.mark.asyncio
async def test_catalog_refresh_uses_workbench_space_before_default_space(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(
        api_token="token",
        host="https://vika.cn",
        default_space_id="spcDefault",
        workbench_space_id="spcWorkbench",
        cache=CatalogCache(db_path=":memory:"),
    )
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.catalog_refresh()

    assert result["space_ids"] == ["spcWorkbench"]


@pytest.mark.asyncio
async def test_catalog_refresh_returns_cache_status_for_explicit_target_space(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodExplicit", "root", "Folder")],
            "Datasheet": [_RawNode("dstExplicit", "table", "Datasheet", "fodExplicit")],
        }
    )
    client = VikaClient(
        api_token="token",
        host="https://vika.cn",
        workbench_space_id="spcWorkbench",
        cache=CatalogCache(db_path=":memory:"),
    )
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.catalog_refresh(space_id="spcExplicit")

    assert result["space_ids"] == ["spcExplicit"]
    assert result["cache"]["space_id"] == "spcExplicit"
    assert result["cache"]["ready_for_discovery"] is True


@pytest.mark.asyncio
async def test_catalog_refresh_failure_and_success_are_scoped_by_target_space(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    seed_catalog_item(cache, client.namespace, "node", "fodA", space_id="spcA")
    seed_catalog_item(cache, client.namespace, "datasheet", "dstA", space_id="spcA")
    failing_nodes = _FakeNodes(
        search_nodes={"Datasheet": [_RawNode("dstB", "table b", "Datasheet", "fodB")]},
        errors={"nodes.asearch:Folder": RuntimeError("spcB folder failed")},
    )
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(failing_nodes))

    failed_b = await client.catalog_refresh(space_id="spcB")

    assert failed_b["error"]["code"] == "catalog_refresh_failed"
    assert client.catalog_status(space_id="spcA")["ready_for_discovery"] is True
    assert client.catalog_status(space_id="spcB")["discovery_status"] == "failed"

    successful_nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodA", "root a", "Folder")],
            "Datasheet": [_RawNode("dstA2", "table a", "Datasheet", "fodA")],
        }
    )
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(successful_nodes))

    refreshed_a = await client.catalog_refresh(space_id="spcA")

    assert refreshed_a["refreshed"] is True
    assert client.catalog_status(space_id="spcA")["ready_for_discovery"] is True
    assert client.catalog_status(space_id="spcB")["discovery_status"] == "failed"


@pytest.mark.asyncio
async def test_required_node_request_failure_preserves_existing_cache_and_marks_failed(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "node",
                "id": "fodOld",
                "space_id": "spc1",
                "name": "old",
                "path": "old",
                "data": {"id": "fodOld", "type": "Folder"},
            },
            {
                "type": "datasheet",
                "id": "dstOld",
                "space_id": "spc1",
                "name": "old table",
                "path": "old/old table",
                "dst_id": "dstOld",
                "data": {"id": "dstOld", "type": "Datasheet"},
            },
        ],
    )
    nodes = _FakeNodes(
        alist_nodes=[_RawNode("fodNew", "new", "Folder")],
        search_nodes={"Datasheet": [_RawNode("dstNew", "new table", "Datasheet", "fodNew")]},
        errors={"nodes.asearch:Folder": RuntimeError("folder search failed")},
    )
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes))

    result = await client.catalog_refresh(space_id="spc1")

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert "nodes.asearch:Folder" in result["error"]["details"]["failed_requests"][0]["request"]
    assert cache.get_item(client.namespace, "node", "fodOld") is not None
    assert cache.get_item(client.namespace, "datasheet", "dstOld") is not None
    assert cache.get_item(client.namespace, "node", "fodNew") is None
    assert cache.get_item(client.namespace, "datasheet", "dstNew") is None
    status = client.catalog_status(space_id="spc1")
    assert status["catalog_status"] == "failed"
    assert "nodes.asearch:Folder" in status["last_refresh_error"]


@pytest.mark.asyncio
async def test_requested_schema_refresh_failure_is_visible_and_marks_failed(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:"))
    datasheet = _FakeDatasheet(fields_error=RuntimeError("schema failed"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes, {"dst1": datasheet}))

    result = await client.catalog_refresh(space_id="spc1", include_fields=True)

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["failed_schema"][0]["datasheet_id"] == "dst1"
    assert "schema failed" in result["error"]["message"]
    status = client.catalog_status(space_id="spc1")
    assert status["catalog_status"] == "failed"
    assert "schema failed" in status["last_refresh_error"]


@pytest.mark.asyncio
async def test_catalog_refresh_include_fields_does_not_fetch_views(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    datasheet = _FakeDatasheet(
        fields=[{"id": "fld1", "name": "Field 1", "isPrimary": True}],
        views=[{"id": "viw1", "name": "View 1"}],
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes, {"dst1": datasheet}))

    result = await client.catalog_refresh(space_id="spc1", include_fields=True, include_views=False)

    assert result["refreshed"] is True
    assert result["counts"]["fields"] == 1
    assert result["counts"]["views"] == 0
    assert datasheet.fields.calls == 1
    assert datasheet.views.calls == 0
    assert client.cache.get_item(client.namespace, "field", "dst1:fld1") is not None
    assert client.cache.get_item(client.namespace, "view", "dst1:viw1") is None


@pytest.mark.asyncio
async def test_catalog_refresh_include_views_does_not_fetch_fields(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    datasheet = _FakeDatasheet(
        fields=[{"id": "fld1", "name": "Field 1", "isPrimary": True}],
        views=[{"id": "viw1", "name": "View 1"}],
    )
    client = VikaClient(api_token="token", host="https://vika.cn", cache=CatalogCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes, {"dst1": datasheet}))

    result = await client.catalog_refresh(space_id="spc1", include_fields=False, include_views=True)

    assert result["refreshed"] is True
    assert result["counts"]["fields"] == 0
    assert result["counts"]["views"] == 1
    assert datasheet.fields.calls == 0
    assert datasheet.views.calls == 1
    assert client.cache.get_item(client.namespace, "field", "dst1:fld1") is None
    assert client.cache.get_item(client.namespace, "view", "dst1:viw1") is not None


@pytest.mark.asyncio
async def test_catalog_refresh_schema_cache_persist_failure_marks_refresh_failed(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    class FailingSchemaCache(CatalogCache):
        def replace_schema_items(self, namespace, datasheet_id, items, item_types=None):
            raise RuntimeError("schema disk full")

    nodes = _FakeNodes(
        search_nodes={
            "Folder": [_RawNode("fodRoot", "root", "Folder")],
            "Datasheet": [_RawNode("dst1", "table", "Datasheet", "fodRoot")],
        }
    )
    datasheet = _FakeDatasheet(fields=[{"id": "fld1", "name": "Field 1"}])
    client = VikaClient(api_token="token", host="https://vika.cn", cache=FailingSchemaCache(db_path=":memory:"))
    monkeypatch.setattr(client, "_ensure_client", lambda: _FakeVika(nodes, {"dst1": datasheet}))

    result = await client.catalog_refresh(space_id="spc1", include_fields=True)

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert result["error"]["details"]["failed_schema"][0]["error"]["details"]["stage"] == "cache_persist"
    assert result["cache"]["catalog_status"] == "failed"


def test_catalog_status_reports_cache_first_state_fields() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:", ttl_hours=1)
    empty = cache.status("namespace")

    assert empty["catalog_status"] == "empty"
    assert empty["counts"] == {}
    assert empty["generation_id"] is None
    assert empty["last_refresh_started_at"] is None
    assert empty["last_refresh_finished_at"] is None
    assert empty["last_refresh_duration_seconds"] is None
    assert empty["last_refresh_error"] is None
    assert empty["ttl_seconds"] == 3600
    assert empty["db_path"] == ":memory:"
    assert empty["health_status"] == "empty"
    assert empty["ready_for_discovery"] is False
    assert empty["discovery_status"] == "empty"
    assert empty["discovery_error"]["code"] == "catalog_not_ready"

    cache.begin_refresh("namespace", None)
    refreshing = cache.status("namespace")
    assert refreshing["health_status"] == "refreshing"
    assert refreshing["catalog_status"] == "empty"
    assert refreshing["ready_for_discovery"] is False
    assert refreshing["discovery_status"] == "empty"
    assert refreshing["discovery_error"]["code"] == "catalog_not_ready"
    assert refreshing["last_refresh_started_at"] is not None

    cache.upsert_items(
        "namespace",
        [
            {
                "type": "node",
                "id": "fodRoot",
                "space_id": "spc1",
                "name": "root",
                "path": "root",
                "data": {"id": "fodRoot", "type": "Folder"},
            }
        ],
    )
    cache.finish_refresh("namespace", None, {"nodes": 1, "datasheets": 0})
    ready = cache.status("namespace")
    assert ready["catalog_status"] == "ready"
    assert ready["health_status"] == "ready"
    assert ready["ready_for_discovery"] is True
    assert ready["discovery_status"] == "ready"
    assert ready["discovery_error"] is None
    assert ready["counts"]["node"] == 1
    assert ready["last_refresh_counts"] == {"nodes": 1, "datasheets": 0}
    assert ready["generation_id"] is not None

    cache.begin_refresh("namespace", None)
    cache.finish_refresh("namespace", None, {"nodes": 0}, error="boom")
    failed = cache.status("namespace")
    assert failed["health_status"] == "failed"
    assert failed["catalog_status"] == "ready"
    assert failed["ready_for_discovery"] is True
    assert failed["discovery_status"] == "ready"
    assert failed["discovery_error"] is None
    assert failed["last_refresh_error"] == "boom"


def test_catalog_readiness_maps_statuses_to_error_codes() -> None:
    from vika_mcp.cache import CatalogCache

    ready = CatalogCache(db_path=":memory:")
    seed_node(ready, "namespace")
    assert ready.readiness("namespace", "spc1")["ready"] is True

    empty = CatalogCache(db_path=":memory:")
    assert empty.readiness("namespace", "spc1")["error"]["code"] == "catalog_not_ready"

    stale = CatalogCache(db_path=":memory:")
    seed_node(stale, "namespace")
    force_stale(stale, "namespace")
    assert stale.readiness("namespace", "spc1")["error"]["code"] == "catalog_stale"

    refreshing = CatalogCache(db_path=":memory:")
    seed_node(refreshing, "namespace")
    refreshing.begin_refresh("namespace", "spc1")
    assert refreshing.readiness("namespace", "spc1")["error"]["code"] == "catalog_refreshing"

    abandoned = CatalogCache(db_path=":memory:", refresh_timeout_seconds=1)
    seed_node(abandoned, "namespace")
    abandoned.begin_refresh("namespace", "spc1")
    with abandoned._connect() as conn:
        conn.execute(
            "UPDATE catalog_refresh_state SET started_at = 0 WHERE namespace = ? AND space_id = ?",
            ("namespace", "spc1"),
        )
    assert abandoned.readiness("namespace", "spc1")["error"]["code"] == "catalog_refresh_abandoned"

    failed = CatalogCache(db_path=":memory:")
    seed_node(failed, "namespace")
    mark_failed(failed, "namespace")
    assert failed.readiness("namespace", "spc1")["error"]["code"] == "catalog_refresh_failed"

    disabled = CatalogCache(db_path=":memory:", enabled=False)
    assert disabled.readiness("namespace", "spc1")["error"]["code"] == "catalog_disabled"


@pytest.mark.asyncio
async def test_nodes_list_cache_only_rejects_fresh_rows_when_catalog_failed(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    seed_node(cache, client.namespace)
    mark_failed(cache, client.namespace, "folder search failed")
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("cache-only failed catalog must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert "nodes" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        ("stale", "catalog_stale"),
        ("refreshing", "catalog_refreshing"),
        ("refresh_abandoned", "catalog_refresh_abandoned"),
    ],
)
async def test_nodes_list_cache_only_rejects_non_ready_catalog_states(monkeypatch, state: str, expected_code: str) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:", refresh_timeout_seconds=1)
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    seed_node(cache, client.namespace)
    if state == "stale":
        force_stale(cache, client.namespace)
    else:
        cache.begin_refresh(client.namespace, "spc1")
        if state == "refresh_abandoned":
            with cache._connect() as conn:
                conn.execute(
                    "UPDATE catalog_refresh_state SET started_at = 0 WHERE namespace = ? AND space_id = ?",
                    (client.namespace, "spc1"),
                )
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("cache-only non-ready catalog must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["error"]["code"] == expected_code
    assert "nodes" not in result


@pytest.mark.asyncio
async def test_nodes_list_cache_only_returns_nodes_only_when_catalog_ready(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    seed_node(cache, client.namespace)
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("ready cache-only discovery must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["source"] == "cache"
    assert {node["id"] for node in result["nodes"]} == {"fodRoot"}
    assert result["catalog"]["catalog_status"] == "ready"


@pytest.mark.asyncio
async def test_nodes_list_cache_only_ignores_stale_schema_rows_for_node_selector(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "node",
                "id": "fodRoot",
                "space_id": "spc1",
                "name": "root",
                "path": "root",
                "data": {"id": "fodRoot", "type": "Folder"},
            },
            {
                "type": "field",
                "id": "fldOld",
                "space_id": "spc1",
                "name": "old schema field",
                "path": "root/客户表/old schema field",
                "dst_id": "dst1",
                "data": {"id": "fldOld", "name": "old schema field"},
            },
        ],
    )
    mark_item_stale(cache, client.namespace, "field", "fldOld")
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("cache-only node selector must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["source"] == "cache"
    assert [node["id"] for node in result["nodes"]] == ["fodRoot"]


@pytest.mark.asyncio
async def test_nodes_list_cache_only_rejects_stale_node_selector_rows(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "node",
                "id": "fodFresh",
                "space_id": "spc1",
                "name": "fresh",
                "path": "fresh",
                "data": {"id": "fodFresh", "type": "Folder"},
            },
            {
                "type": "node",
                "id": "fodOld",
                "space_id": "spc1",
                "name": "old",
                "path": "old",
                "data": {"id": "fodOld", "type": "Folder"},
            },
        ],
    )
    mark_item_stale(cache, client.namespace, "node", "fodOld")
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("cache-only stale node selector must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["error"]["code"] == "catalog_stale"
    assert "nodes" not in result


@pytest.mark.asyncio
async def test_nodes_list_cache_only_rejects_invalid_node_selector_timestamp(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "node",
                "id": "fodFresh",
                "space_id": "spc1",
                "name": "fresh",
                "path": "fresh",
                "data": {"id": "fodFresh", "type": "Folder"},
            },
            {
                "type": "node",
                "id": "fodBad",
                "space_id": "spc1",
                "name": "bad",
                "path": "bad",
                "data": {"id": "fodBad", "type": "Folder"},
            },
        ],
    )
    set_item_updated_at(cache, client.namespace, "node", "fodBad", "not-a-timestamp")
    monkeypatch.setattr(client, "_ensure_client", lambda: pytest.fail("cache-only invalid timestamp selector must not open the Vika API"))

    result = await client.nodes_list("spc1", cache_only=True)

    assert result["error"]["code"] == "catalog_stale"
    assert "nodes" not in result


def test_catalog_search_and_get_do_not_return_rows_when_catalog_failed() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dst1",
                "space_id": "spc1",
                "name": "客户表",
                "path": "root/客户表",
                "dst_id": "dst1",
                "data": {"id": "dst1", "type": "Datasheet"},
            }
        ],
    )
    mark_failed(cache, client.namespace)

    searched = client.catalog_search("客户", space_id="spc1")
    fetched = client.catalog_get("datasheet", "dst1")

    assert searched["error"]["code"] == "catalog_refresh_failed"
    assert "matches" not in searched
    assert fetched["error"]["code"] == "catalog_refresh_failed"
    assert "item" not in fetched


def test_namespace_catalog_search_rejects_rows_from_failed_scoped_refresh_state() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstFailed",
                "space_id": "spcFailed",
                "name": "客户表",
                "path": "failed/客户表",
                "dst_id": "dstFailed",
                "data": {"id": "dstFailed", "type": "Datasheet"},
            }
        ],
    )
    mark_failed(cache, client.namespace, space_id="spcFailed")

    searched = client.catalog_search("客户")

    assert searched["error"]["code"] == "catalog_refresh_failed"
    assert searched["error"]["details"]["space_id"] == "spcFailed"
    assert "matches" not in searched


def test_namespace_catalog_search_rejects_when_any_selector_space_is_refreshing() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstReady",
                "space_id": "spcReady",
                "name": "客户表",
                "path": "ready/客户表",
                "dst_id": "dstReady",
                "data": {"id": "dstReady", "type": "Datasheet"},
            },
            {
                "type": "datasheet",
                "id": "dstRefreshing",
                "space_id": "spcRefreshing",
                "name": "库存表",
                "path": "refreshing/库存表",
                "dst_id": "dstRefreshing",
                "data": {"id": "dstRefreshing", "type": "Datasheet"},
            },
        ],
    )
    cache.begin_refresh(client.namespace, "spcRefreshing")

    searched = client.catalog_search("客户")

    assert searched["error"]["code"] == "catalog_refreshing"
    assert searched["error"]["details"]["space_id"] == "spcRefreshing"
    assert "matches" not in searched


def test_namespace_catalog_search_rejects_failed_scoped_refresh_state_without_cached_rows() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstReady",
                "space_id": "spcReady",
                "name": "客户表",
                "path": "ready/客户表",
                "dst_id": "dstReady",
                "data": {"id": "dstReady", "type": "Datasheet"},
            }
        ],
    )
    mark_failed(cache, client.namespace, space_id="spcFailed")

    searched = client.catalog_search("客户")

    assert searched["error"]["code"] == "catalog_refresh_failed"
    assert searched["error"]["details"]["space_id"] == "spcFailed"
    assert "matches" not in searched


def test_namespace_catalog_status_uses_same_scoped_readiness_as_search() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstReady",
                "space_id": "spcReady",
                "name": "客户表",
                "path": "ready/客户表",
                "dst_id": "dstReady",
                "data": {"id": "dstReady", "type": "Datasheet"},
            }
        ],
    )
    mark_failed(cache, client.namespace, space_id="spcFailed")

    status = client.catalog_status()
    searched = client.catalog_search("客户")

    assert status["ready_for_discovery"] is False
    assert status["catalog_status"] == "failed"
    assert status["discovery_status"] == "failed"
    assert status["discovery_error"]["code"] == searched["error"]["code"] == "catalog_refresh_failed"
    assert status["discovery_error"]["details"]["space_id"] == searched["error"]["details"]["space_id"] == "spcFailed"


def test_namespace_catalog_status_uses_same_gate_when_rows_are_stale_and_scope_failed() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstReady",
                "space_id": "spcReady",
                "name": "客户表",
                "path": "ready/客户表",
                "dst_id": "dstReady",
                "data": {"id": "dstReady", "type": "Datasheet"},
            }
        ],
    )
    force_stale(cache, client.namespace)
    mark_failed(cache, client.namespace, space_id="spcFailed")

    status = client.catalog_status()
    searched = client.catalog_search("客户")

    assert searched["error"]["code"] == "catalog_refresh_failed"
    assert status["ready_for_discovery"] is False
    assert status["catalog_status"] == "failed"
    assert status["discovery_status"] == "failed"
    assert status["discovery_error"]["code"] == searched["error"]["code"]
    assert status["discovery_error"]["details"]["space_id"] == searched["error"]["details"]["space_id"] == "spcFailed"


def test_namespace_catalog_search_blocks_when_refresh_state_scope_cannot_be_checked(monkeypatch) -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstReady",
                "space_id": "spcReady",
                "name": "客户表",
                "path": "ready/客户表",
                "dst_id": "dstReady",
                "data": {"id": "dstReady", "type": "Datasheet"},
            }
        ],
    )

    def fail_state_list(namespace):
        raise RuntimeError("refresh state unavailable")

    monkeypatch.setattr(cache, "_list_scoped_refresh_space_ids", fail_state_list)

    searched = client.catalog_search("客户")

    assert searched["error"]["code"] == "catalog_refresh_failed"
    assert "refresh state unavailable" in searched["error"]["details"]["catalog_status"]["last_refresh_error"]
    assert "matches" not in searched


def test_namespace_catalog_get_rejects_field_from_failed_scoped_refresh_state() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "field",
                "id": "dstFailed:fldName",
                "space_id": "spcFailed",
                "name": "客户名称",
                "path": "failed/客户表/客户名称",
                "dst_id": "dstFailed",
                "data": {"id": "fldName", "name": "客户名称"},
            }
        ],
    )
    mark_failed(cache, client.namespace, space_id="spcFailed")

    fetched = client.catalog_get("field", "dstFailed:fldName")

    assert fetched["error"]["code"] == "catalog_refresh_failed"
    assert fetched["error"]["details"]["space_id"] == "spcFailed"
    assert "item" not in fetched


def test_catalog_search_rejects_stale_requested_space_even_when_namespace_has_fresh_rows() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstOld",
                "space_id": "spcOld",
                "name": "旧客户表",
                "path": "root/旧客户表",
                "dst_id": "dstOld",
                "data": {"id": "dstOld", "type": "Datasheet"},
            },
            {
                "type": "node",
                "id": "fodFresh",
                "space_id": "spcFresh",
                "name": "fresh",
                "path": "fresh",
                "data": {"id": "fodFresh", "type": "Folder"},
            },
        ],
    )
    mark_space_stale(cache, client.namespace, "spcOld")

    readiness = cache.readiness(client.namespace, "spcOld")
    searched = client.catalog_search("客户", space_id="spcOld")

    assert readiness["error"]["code"] == "catalog_stale"
    assert searched["error"]["code"] == "catalog_stale"
    assert "matches" not in searched


def test_catalog_get_rejects_stale_item_even_when_namespace_has_fresh_rows() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstOld",
                "space_id": "spcOld",
                "name": "旧客户表",
                "path": "root/旧客户表",
                "dst_id": "dstOld",
                "data": {"id": "dstOld", "type": "Datasheet"},
            },
            {
                "type": "node",
                "id": "fodFresh",
                "space_id": "spcFresh",
                "name": "fresh",
                "path": "fresh",
                "data": {"id": "fodFresh", "type": "Folder"},
            },
        ],
    )
    mark_space_stale(cache, client.namespace, "spcOld")

    fetched = client.catalog_get("datasheet", "dstOld")

    assert fetched["error"]["code"] == "catalog_stale"
    assert "item" not in fetched


def test_catalog_get_rejects_fresh_datasheet_when_same_space_selector_has_stale_sibling() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstFresh",
                "space_id": "spc1",
                "name": "fresh",
                "path": "root/fresh",
                "dst_id": "dstFresh",
                "data": {"id": "dstFresh", "type": "Datasheet"},
            },
            {
                "type": "datasheet",
                "id": "dstOld",
                "space_id": "spc1",
                "name": "old",
                "path": "root/old",
                "dst_id": "dstOld",
                "data": {"id": "dstOld", "type": "Datasheet"},
            },
        ],
    )
    mark_item_stale(cache, client.namespace, "datasheet", "dstOld")

    fetched = client.catalog_get("datasheet", "dstFresh")

    assert fetched["error"]["code"] == "catalog_stale"
    assert "item" not in fetched


def test_catalog_get_does_not_reject_fresh_datasheet_for_stale_sibling_in_other_space() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstFresh",
                "space_id": "spcFresh",
                "name": "fresh",
                "path": "root/fresh",
                "dst_id": "dstFresh",
                "data": {"id": "dstFresh", "type": "Datasheet"},
            },
            {
                "type": "datasheet",
                "id": "dstOld",
                "space_id": "spcOld",
                "name": "old",
                "path": "root/old",
                "dst_id": "dstOld",
                "data": {"id": "dstOld", "type": "Datasheet"},
            },
        ],
    )
    mark_item_stale(cache, client.namespace, "datasheet", "dstOld")

    fetched = client.catalog_get("datasheet", "dstFresh")

    assert fetched["source"] == "cache"
    assert fetched["item"]["id"] == "dstFresh"
    assert fetched["catalog"]["catalog_status"] == "ready"


def test_catalog_get_uses_dst_selector_for_field_readiness() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "field",
                "id": "dst1:fldFresh",
                "space_id": "spc1",
                "name": "fresh",
                "path": "dst1/fresh",
                "dst_id": "dst1",
                "data": {"id": "fldFresh", "name": "fresh"},
            },
            {
                "type": "field",
                "id": "dst1:fldOld",
                "space_id": "spc1",
                "name": "old",
                "path": "dst1/old",
                "dst_id": "dst1",
                "data": {"id": "fldOld", "name": "old"},
            },
            {
                "type": "field",
                "id": "dst2:fldOld",
                "space_id": "spc1",
                "name": "other old",
                "path": "dst2/old",
                "dst_id": "dst2",
                "data": {"id": "fldOld", "name": "old"},
            },
        ],
    )
    mark_item_stale(cache, client.namespace, "field", "dst1:fldOld")

    blocked = client.catalog_get("field", "dst1:fldFresh")

    assert blocked["error"]["code"] == "catalog_stale"
    assert "item" not in blocked

    set_item_updated_at(cache, client.namespace, "field", "dst1:fldOld", 9999999999)
    mark_item_stale(cache, client.namespace, "field", "dst2:fldOld")

    fetched = client.catalog_get("field", "dst1:fldFresh")

    assert fetched["source"] == "cache"
    assert fetched["item"]["id"] == "dst1:fldFresh"
    assert fetched["catalog"]["catalog_status"] == "ready"


def test_catalog_search_rejects_zero_timestamp_rows_in_search_selector() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dstFresh",
                "space_id": "spc1",
                "name": "client table",
                "path": "root/client table",
                "dst_id": "dstFresh",
                "data": {"id": "dstFresh", "type": "Datasheet"},
            },
            {
                "type": "datasheet",
                "id": "dstOld",
                "space_id": "spc1",
                "name": "inventory table",
                "path": "root/inventory table",
                "dst_id": "dstOld",
                "data": {"id": "dstOld", "type": "Datasheet"},
            },
        ],
    )
    mark_item_stale(cache, client.namespace, "datasheet", "dstOld")

    searched = client.catalog_search("client", space_id="spc1")

    assert searched["error"]["code"] == "catalog_stale"
    assert "matches" not in searched


def test_catalog_status_marks_stale_refresh_as_abandoned() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:", refresh_timeout_seconds=1)
    cache.begin_refresh("namespace", None)
    with cache._connect() as conn:
        conn.execute(
            "UPDATE catalog_refresh_state SET started_at = 0 WHERE namespace = ? AND space_id = ?",
            ("namespace", ""),
        )

    status = cache.status("namespace")

    assert status["health_status"] == "refresh_abandoned"
    assert status["catalog_status"] == "empty"
    assert status["ready_for_discovery"] is False
    assert status["discovery_error"]["code"] == "catalog_not_ready"
    assert status["last_refresh_finished_at"] is not None
    assert "abandoned" in status["last_refresh_error"]


def test_catalog_clear_full_namespace_resets_refresh_state() -> None:
    from vika_mcp.cache import CatalogCache

    cache = CatalogCache(db_path=":memory:")
    cache.upsert_items(
        "namespace",
        [
            {
                "type": "node",
                "id": "fodRoot",
                "space_id": "spc1",
                "name": "root",
                "path": "root",
                "data": {"id": "fodRoot", "type": "Folder"},
            }
        ],
    )
    cache.begin_refresh("namespace", "spc1")
    cache.finish_refresh("namespace", "spc1", {"nodes": 1})

    cleared = cache.clear("namespace")
    status = cache.status("namespace")

    assert cleared == 1
    assert status["catalog_status"] == "empty"
    assert status["generation_id"] is None
    assert status["last_refresh_error"] is None
    assert status["last_refresh_counts"] == {}


@pytest.mark.asyncio
async def test_hidden_catalog_refresh_returns_scope_error_without_exception(monkeypatch) -> None:
    from vika_mcp.runtime.services import RuntimeServices
    from vika_mcp.tools import vika_tools

    class FakeClient:
        async def catalog_refresh(self, space_id=None, include_fields=False, include_views=False, force=False):
            return {"error": {"code": "catalog_refresh_scope_required", "message": "bounded scope required"}}

    monkeypatch.setattr(vika_tools, "_CLIENT", FakeClient())

    result = await vika_tools.vika_catalog_refresh({}, RuntimeServices())

    assert result["error"]["code"] == "catalog_refresh_scope_required"


def test_catalog_search_and_get_return_freshness_metadata() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dst1",
                "space_id": "spc1",
                "name": "客户表",
                "path": "root/客户表",
                "dst_id": "dst1",
                "data": {"id": "dst1", "type": "Datasheet"},
            }
        ],
    )

    searched = client.catalog_search("客户", space_id="spc1")
    fetched = client.catalog_get("datasheet", "dst1")

    assert searched["source"] == "cache"
    assert searched["catalog"]["catalog_status"] == "ready"
    assert searched["catalog"]["generation_id"] is not None
    assert fetched["source"] == "cache"
    assert fetched["catalog"]["catalog_status"] == "ready"
    assert fetched["catalog"]["generation_id"] is not None


def test_selector_readiness_ignores_namespace_diagnostic_refresh_state() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "datasheet",
                "id": "dst1",
                "space_id": "spc1",
                "name": "客户表",
                "path": "root/客户表",
                "dst_id": "dst1",
                "data": {"id": "dst1", "type": "Datasheet"},
            },
            {
                "type": "field",
                "id": "dst1:fld1",
                "space_id": "spc1",
                "name": "客户字段",
                "path": "dst1/客户字段",
                "dst_id": "dst1",
                "data": {"id": "fld1", "name": "客户字段"},
            },
        ],
    )
    cache.begin_refresh(client.namespace, None)
    cache.finish_refresh(client.namespace, None, {"nodes": 0}, error="namespace diagnostic failed")

    searched = client.catalog_search("客户")
    fetched_field = client.catalog_get("field", "dst1:fld1")

    assert searched["source"] == "cache"
    assert [item["id"] for item in searched["matches"]] == ["dst1"]
    assert fetched_field["source"] == "cache"
    assert fetched_field["item"]["id"] == "dst1:fld1"
