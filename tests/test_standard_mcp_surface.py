from __future__ import annotations

import pytest


def ready_discovery_catalog() -> dict:
    return {
        "readiness_type": "discovery",
        "readiness_status": "ready",
        "catalog_status": "ready",
        "ready_for_discovery": True,
    }


@pytest.mark.anyio
async def test_standard_server_lists_only_visible_meta_tools_by_default() -> None:
    from vika_mcp.standard_server import create_standard_mcp

    server = create_standard_mcp()
    tools = await server.list_tools()
    names = {tool.name for tool in tools}

    assert {
        "vika_guide",
        "vika_resolve_datasheet",
        "vika_search_tools",
        "vika_route_task",
        "vika_describe_tool",
        "vika_call_tool",
        "vika_list_domains",
        "vika_activate_domain",
        "vika_artifact_head",
        "vika_artifact_search",
        "vika_artifact_read",
        "vika_artifact_status",
    }.issubset(names)
    assert "vika.records.query" not in names
    assert "vika.records.read_all" not in names


def test_hidden_registry_contains_business_tools_without_visible_exposure() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    hidden_names = {tool.name for tool in registry.list_hidden_tools(include_unavailable=True)}
    visible_names = {tool.name for tool in registry.list_visible_tools(include_unavailable=True)}

    assert "vika.records.query" in hidden_names
    assert "vika.schema.get" in hidden_names
    assert "vika_export_records" in hidden_names
    assert "vika.records.query" not in visible_names
    assert "vika.records.read_all" in hidden_names


def test_all_write_tools_are_in_write_domain() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    write_tools = [tool for tool in registry.list_hidden_tools(include_unavailable=True) if tool.write]

    assert write_tools
    assert {tool.name for tool in write_tools if tool.domain != "write"} == set()


def test_hidden_tool_contract_matrix_has_no_known_drift_patterns() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.scope import WORKBENCH_BLOCKED_TOOLS

    registry = build_hidden_registry()
    tools = {tool.name: tool for tool in registry.list_hidden_tools(include_unavailable=True)}

    assert "vika.records.read_all" in tools
    assert "vika.records.read_all" not in {
        candidate.name
        for candidate in registry.list_hidden_tools(include_unavailable=True)
        if candidate.name not in WORKBENCH_BLOCKED_TOOLS and candidate.name != "vika.records.read_all"
    }

    for name, spec in tools.items():
        schema = spec.input_schema or {}
        required = set(schema.get("required") or [])
        properties = set((schema.get("properties") or {}).keys())
        assert required <= properties, name
        if spec.write:
            assert spec.domain == "write", name
            assert spec.read_only is False, name
        if name == "vika_export_records":
            assert "max_records" in required
            assert spec.result_policy["mode"] == "artifact"
            assert spec.result_policy["default_format"] == "csv"
            assert spec.result_policy["supported_formats"] == ["csv", "jsonl"]
            assert "format" not in spec.result_policy


def test_datasheets_create_schema_requires_folder_id() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    spec, _handler = registry.get("vika.datasheets.create")

    assert "folder_id" in spec.input_schema["required"]


def test_visible_artifact_tool_descriptions_are_csv_jsonl_or_format_neutral() -> None:
    from vika_mcp.runtime.meta_tools import visible_meta_tool_definitions

    tools = {tool.name: tool for tool in visible_meta_tool_definitions()}

    for name in ["vika_artifact_search", "vika_artifact_read"]:
        description = tools[name].description
        assert "JSONL export artifact" not in description
        assert "CSV/JSONL export artifact" in description or "export artifact" in description


def test_visible_meta_tool_schemas_express_capability_search_and_structured_route() -> None:
    from vika_mcp.runtime.meta_tools import visible_meta_tool_definitions

    tools = {tool.name: tool for tool in visible_meta_tool_definitions()}
    search_schema = tools["vika_search_tools"].input_schema
    route_schema = tools["vika_route_task"].input_schema

    assert "capability" in search_schema["properties"]
    assert "task" not in search_schema["properties"]
    assert "task_kind" in route_schema["required"]
    assert "task_kind" in route_schema["properties"]
    assert "datasheet_query" in route_schema["properties"]
    assert "datasheet_id" in route_schema["properties"]
    assert "task" not in route_schema["properties"]


def test_workbench_scope_uses_canonical_catalog_ready_check() -> None:
    import inspect

    from vika_mcp.runtime.scope import WorkbenchScope

    error_source = inspect.getsource(WorkbenchScope._catalog_error_from_result)
    ready_source = inspect.getsource(WorkbenchScope._catalog_is_canonical_ready)

    assert "_catalog_is_canonical_ready(" in error_source
    assert "ready_for_discovery" in ready_source
    assert "catalog_status" in ready_source
    assert "readiness_status" in ready_source
    assert "discovery_status" in ready_source
    assert 'catalog.get("readiness_type") == "discovery" and catalog.get("readiness_status") == "ready"' not in error_source


def test_cli_accepts_standard_mcp_transport_options() -> None:
    from vika_mcp.__main__ import parse_args

    args = parse_args(["--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8080"])

    assert args.transport == "streamable-http"
    assert args.listen_host == "127.0.0.1"
    assert args.listen_port == 8080
    assert args.catalog_refresh is False
    assert args.catalog_status is False


def test_cli_accepts_catalog_maintenance_options() -> None:
    from vika_mcp.__main__ import parse_args

    args = parse_args(["--catalog-refresh", "--space-id", "spc1", "--include-fields", "--force"])

    assert args.catalog_refresh is True
    assert args.catalog_status is False
    assert args.space_id == "spc1"
    assert args.include_fields is True
    assert args.include_views is False
    assert args.force is True


@pytest.mark.anyio
async def test_catalog_maintenance_refresh_requires_bounded_space(monkeypatch) -> None:
    from vika_mcp.__main__ import _run_catalog_maintenance, parse_args
    from vika_mcp.tools import vika_tools

    for key in [
        "VIKAMCP_CONFIG",
        "VIKAMCP_VIKA__WORKBENCH_SPACE_ID",
        "VIKAMCP_VIKA__DEFAULT_SPACE_ID",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VIKAMCP_CACHE__DB_PATH", ":memory:")
    monkeypatch.setattr(
        vika_tools.VikaClient,
        "catalog_refresh",
        lambda *args, **kwargs: pytest.fail("unbounded maintenance refresh must not call client refresh"),
    )

    result = await _run_catalog_maintenance(parse_args(["--catalog-refresh"]))

    assert result["error"]["code"] == "catalog_refresh_scope_required"


@pytest.mark.anyio
async def test_catalog_maintenance_refresh_target_precedence(monkeypatch) -> None:
    from vika_mcp.__main__ import _run_catalog_maintenance, parse_args
    from vika_mcp.tools import vika_tools

    captured: list[str | None] = []

    async def fake_catalog_refresh(self, space_id=None, include_fields=False, include_views=False, force=False):
        captured.append(space_id)
        return {"refreshed": True, "space_ids": [space_id], "counts": {}}

    monkeypatch.setenv("VIKAMCP_CACHE__DB_PATH", ":memory:")
    monkeypatch.setenv("VIKAMCP_VIKA__API_TOKEN", "token-for-test")
    monkeypatch.setattr(vika_tools.VikaClient, "catalog_refresh", fake_catalog_refresh)

    monkeypatch.setenv("VIKAMCP_VIKA__WORKBENCH_SPACE_ID", "spcWorkbench")
    monkeypatch.setenv("VIKAMCP_VIKA__DEFAULT_SPACE_ID", "spcDefault")
    await _run_catalog_maintenance(parse_args(["--catalog-refresh", "--space-id", "spcExplicit"]))

    await _run_catalog_maintenance(parse_args(["--catalog-refresh"]))

    monkeypatch.delenv("VIKAMCP_VIKA__WORKBENCH_SPACE_ID", raising=False)
    await _run_catalog_maintenance(parse_args(["--catalog-refresh"]))

    assert captured == ["spcExplicit", "spcWorkbench", "spcDefault"]


@pytest.mark.anyio
async def test_catalog_maintenance_refresh_disabled_cache_rejects_without_api(monkeypatch) -> None:
    from vika_mcp.__main__ import _run_catalog_maintenance, parse_args
    from vika_mcp.tools import vika_tools

    monkeypatch.setenv("VIKAMCP_CACHE__ENABLED", "false")
    monkeypatch.setenv("VIKAMCP_CACHE__DB_PATH", ":memory:")
    monkeypatch.setattr(
        vika_tools.VikaClient,
        "_ensure_client",
        lambda self: pytest.fail("disabled cache maintenance refresh must not open Vika API"),
    )

    result = await _run_catalog_maintenance(parse_args(["--catalog-refresh", "--space-id", "spc1"]))

    assert result["error"]["code"] == "catalog_disabled"
    assert "refreshed" not in result
    assert result["cache"]["enabled"] is False


@pytest.mark.anyio
async def test_catalog_maintenance_status_honors_space_id_override(monkeypatch) -> None:
    from vika_mcp.__main__ import _run_catalog_maintenance, parse_args
    from vika_mcp.tools import vika_tools

    captured: list[str | None] = []

    def fake_catalog_status(self, space_id=None):
        captured.append(space_id)
        return {"enabled": True, "space_id": space_id}

    monkeypatch.setenv("VIKAMCP_CACHE__DB_PATH", ":memory:")
    monkeypatch.setenv("VIKAMCP_VIKA__API_TOKEN", "token-for-test")
    monkeypatch.setattr(vika_tools.VikaClient, "catalog_status", fake_catalog_status)

    explicit = await _run_catalog_maintenance(parse_args(["--catalog-status", "--space-id", "spcExplicit"]))
    default = await _run_catalog_maintenance(parse_args(["--catalog-status"]))

    assert explicit["space_id"] == "spcExplicit"
    assert default["space_id"] is None
    assert captured == ["spcExplicit", None]


def test_non_local_streamable_http_requires_independent_mcp_bearer_token(monkeypatch) -> None:
    from vika_mcp.standard_server import create_standard_mcp

    monkeypatch.delenv("VIKAMCP_MCP_BEARER_TOKEN", raising=False)
    stdio_server = create_standard_mcp(host="0.0.0.0", port=8080, transport="stdio")
    assert stdio_server.settings.auth is None

    with pytest.raises(RuntimeError, match="VIKAMCP_MCP_BEARER_TOKEN"):
        create_standard_mcp(host="0.0.0.0", port=8080, transport="streamable-http")

    monkeypatch.setenv("VIKAMCP_MCP_BEARER_TOKEN", "transport-token-for-test")
    server = create_standard_mcp(host="0.0.0.0", port=8080, transport="streamable-http")
    assert server.settings.auth is not None


def test_standard_server_instructions_use_payload_hash_confirmation_protocol() -> None:
    from vika_mcp.standard_server import create_standard_mcp

    server = create_standard_mcp()
    instructions = server.instructions

    assert "confirmation_context" in instructions
    assert "confirmed_payload_hash" in instructions
    assert "cache-only" in instructions
    assert "must not trigger catalog refresh" in instructions
    assert "readiness gate" in instructions
    assert "LLM extracts the business table name" in instructions
    assert "capability-only" in instructions
    assert "structured workflow planner" in instructions
    assert "exact confirmation summary" not in instructions
    assert "confirmation summary" not in instructions


def test_folder_workbench_examples_include_required_space_id() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    docs = [
        root / "README.md",
        root / "docs" / "astrbot-usage.md",
        root / "docs" / "standard-mcp-refactor-plan.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "VIKAMCP_VIKA__WORKBENCH_SPACE_ID" in text


def test_old_custom_http_protocol_is_not_a_runtime_entrypoint() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    assert not (root / "routes.py").exists()
    assert not (root / "server.py").exists()
    assert not (root / "runtime" / "executor.py").exists()
    assert "/mcp/v1/" not in (root / "README.md").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_meta_tools_describe_and_call_hidden_read_tool() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.types import ToolDefinition

    registry = build_hidden_registry(include_vika=False)
    registry.register(
        ToolDefinition(
            name="hidden.echo",
            description="Echo a value for tests.",
            input_schema={
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
                "additionalProperties": False,
            },
            domain="query",
            risk="low",
            exposure="hidden",
            result_policy={"mode": "inline", "max_chars": 20000},
            aliases=["echo"],
        ),
        lambda args: {"echo": args["value"]},
    )

    runtime = MetaToolRuntime(registry)

    described = await runtime.describe_tool("hidden.echo")
    assert described["name"] == "hidden.echo"
    assert described["input_schema"]["required"] == ["value"]

    result = await runtime.call_tool("hidden.echo", {"value": "ok"})
    assert result == {"echo": "ok"}


@pytest.mark.anyio
async def test_call_tool_requires_resolve_before_datasheet_scoped_hidden_calls() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.types import ToolDefinition

    registry = build_hidden_registry(include_vika=False)
    registry.register(
        ToolDefinition(
            name="hidden.schema",
            description="Read schema.",
            input_schema={
                "type": "object",
                "required": ["datasheet_id"],
                "properties": {"datasheet_id": {"type": "string"}},
                "additionalProperties": False,
            },
            domain="schema",
            risk="low",
            exposure="hidden",
            result_policy={"mode": "inline", "max_chars": 20000},
        ),
        lambda args: {"datasheet_id": args["datasheet_id"]},
    )
    registry.register(
        ToolDefinition(
            name="vika.spaces.list",
            description="List spaces.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain="connection",
            exposure="hidden",
        ),
        lambda args: {"spaces": [{"id": "spc1"}]},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={"type": "object", "required": ["space_id"], "properties": {"space_id": {"type": "string"}}, "additionalProperties": True},
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                {"type": "datasheet", "id": "dstAllowed", "parent_id": "fodRoot", "name": "allowed", "path": "root/allowed", "dst_id": "dstAllowed"},
            ],
            "catalog": ready_discovery_catalog(),
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    blocked = await runtime.call_tool("hidden.schema", {"datasheet_id": "dstBlocked"})
    assert blocked["error"]["code"] == "datasheet_not_resolved"

    await runtime.resolve_datasheet(datasheet_id="dstAllowed")
    allowed = await runtime.call_tool("hidden.schema", {"datasheet_id": "dstAllowed"})
    assert allowed == {"datasheet_id": "dstAllowed"}


@pytest.mark.anyio
async def test_live_discovery_tools_are_not_model_entry_tools() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.types import ToolDefinition

    registry = build_hidden_registry(include_vika=False)
    registry.register(
        ToolDefinition(
            name="vika.spaces.list",
            description="List all spaces.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain="connection",
            risk="low",
            exposure="hidden",
            result_policy={"mode": "inline"},
        ),
        lambda args: {"spaces": ["outside-scope"]},
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fod6mElQf7PFD")

    result = await runtime.call_tool("vika.spaces.list", {})

    assert result["error"]["code"] == "tool_not_model_entry"


@pytest.mark.anyio
async def test_resolve_datasheet_uses_workbench_folder_scope() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    called = {"spaces": 0, "nodes": 0}
    node_args = []
    registry.register(
        ToolDefinition(
            name="vika.spaces.list",
            description="List spaces.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain="connection",
            exposure="hidden",
        ),
        lambda args: called.__setitem__("spaces", called["spaces"] + 1) or {"spaces": [{"id": "spc1", "name": "space"}]},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: (
            called.__setitem__("nodes", called["nodes"] + 1)
            or node_args.append(dict(args))
            or {
                "nodes": [
                    {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                    {"type": "datasheet", "id": "dstInScope", "parent_id": "fodRoot", "name": "客户表", "path": "root/客户表", "dst_id": "dstInScope"},
                    {"type": "datasheet", "id": "dstOutside", "parent_id": "fodOther", "name": "外部表", "path": "other/外部表", "dst_id": "dstOutside"},
                ],
                "catalog": ready_discovery_catalog(),
            }
        ),
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    resolved = await runtime.resolve_datasheet(table_name="客户表")
    assert resolved["selected"]["datasheet_id"] == "dstInScope"
    assert resolved["need_user_choice"] is False
    assert called["spaces"] == 0
    assert called["nodes"] == 1
    assert node_args == [{"space_id": "spc1", "use_cache": True, "force_refresh": False, "cache_only": True}]

    rejected = await runtime.resolve_datasheet(datasheet_id="dstOutside")
    assert rejected["selected"] is None
    assert rejected["need_user_choice"] is True
    assert rejected["error"]["code"] == "datasheet_out_of_workbench_scope"


@pytest.mark.anyio
async def test_resolve_datasheet_cache_miss_does_not_fallback_to_refresh() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    node_args = []
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "use_cache": {"type": "boolean"},
                    "force_refresh": {"type": "boolean"},
                    "cache_only": {"type": "boolean"},
                },
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: node_args.append(dict(args))
        or {
            "error": {
                "code": "catalog_not_ready",
                "message": "The workbench catalog is not ready for cache-only discovery.",
                "details": {"catalog_status": "empty"},
            }
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    result = await runtime.resolve_datasheet(table_name="客户表")

    assert node_args == [{"space_id": "spc1", "use_cache": True, "force_refresh": False, "cache_only": True}]
    assert result["selected"] is None
    assert result["need_user_choice"] is True
    assert result["error"]["code"] == "catalog_not_ready"


@pytest.mark.anyio
async def test_resolve_datasheet_rejects_nodes_returned_with_non_ready_catalog() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                {"type": "datasheet", "id": "dst1", "parent_id": "fodRoot", "name": "客户表", "path": "root/客户表", "dst_id": "dst1"},
            ],
            "catalog": {
                "readiness_type": "discovery",
                "readiness_status": "failed",
                "catalog_status": "failed",
                "ready_for_discovery": False,
                "last_refresh_error": "folder search failed",
            },
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    result = await runtime.resolve_datasheet(table_name="客户表")

    assert result["selected"] is None
    assert result["error"]["code"] == "catalog_refresh_failed"


@pytest.mark.anyio
async def test_resolve_datasheet_rejects_inconsistent_ready_catalog_metadata() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                {"type": "datasheet", "id": "dst1", "parent_id": "fodRoot", "name": "客户表", "path": "root/客户表", "dst_id": "dst1"},
            ],
            "catalog": {
                "readiness_type": "discovery",
                "readiness_status": "ready",
                "discovery_status": "ready",
                "catalog_status": "failed",
                "ready_for_discovery": False,
                "last_refresh_error": "catalog metadata is inconsistent",
            },
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    result = await runtime.resolve_datasheet(table_name="客户表")

    assert result["selected"] is None
    assert result["error"]["code"] == "catalog_refresh_failed"


@pytest.mark.anyio
async def test_resolve_datasheet_retries_after_catalog_error_in_same_runtime() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    calls = {"nodes": 0}
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: (
            calls.__setitem__("nodes", calls["nodes"] + 1)
            or (
                {
                    "error": {
                        "code": "catalog_not_ready",
                        "message": "The workbench catalog is not ready.",
                    }
                }
                if calls["nodes"] == 1
                else {
                    "nodes": [
                        {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                        {"type": "datasheet", "id": "dst1", "parent_id": "fodRoot", "name": "客户表", "path": "root/客户表", "dst_id": "dst1"},
                    ],
                    "catalog": ready_discovery_catalog(),
                }
            )
        ),
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    first = await runtime.resolve_datasheet(table_name="客户表")
    second = await runtime.resolve_datasheet(table_name="客户表")

    assert first["error"]["code"] == "catalog_not_ready"
    assert second["selected"]["datasheet_id"] == "dst1"
    assert calls["nodes"] == 2


@pytest.mark.anyio
async def test_resolve_datasheet_retries_after_non_ready_catalog_result_in_same_runtime() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    calls = {"nodes": 0}
    ready_nodes = [
        {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
        {"type": "datasheet", "id": "dst1", "parent_id": "fodRoot", "name": "客户表", "path": "root/客户表", "dst_id": "dst1"},
    ]
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: (
            calls.__setitem__("nodes", calls["nodes"] + 1)
            or (
                {
                    "nodes": ready_nodes,
                    "catalog": {
                        "readiness_type": "discovery",
                        "readiness_status": "failed",
                        "catalog_status": "failed",
                        "ready_for_discovery": False,
                        "last_refresh_error": "folder search failed",
                    },
                }
                if calls["nodes"] == 1
                else {"nodes": ready_nodes, "catalog": ready_discovery_catalog()}
            )
        ),
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    first = await runtime.resolve_datasheet(table_name="客户表")
    second = await runtime.resolve_datasheet(table_name="客户表")

    assert first["error"]["code"] == "catalog_refresh_failed"
    assert second["selected"]["datasheet_id"] == "dst1"
    assert calls["nodes"] == 2


@pytest.mark.anyio
async def test_resolve_datasheet_matches_catalog_status_discovery_readiness() -> None:
    from vika_mcp.cache import CatalogCache
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition
    from vika_mcp.tools.vika_tools import VikaClient

    cache = CatalogCache(db_path=":memory:")
    client = VikaClient(api_token="token", host="https://vika.cn", cache=cache)
    cache.upsert_items(
        client.namespace,
        [
            {
                "type": "field",
                "id": "dst1:fld1",
                "space_id": "spc1",
                "name": "客户字段",
                "path": "客户表/客户字段",
                "dst_id": "dst1",
                "data": {"id": "fld1", "name": "客户字段"},
            }
        ],
    )
    status = client.catalog_status()
    assert status["health_status"] == "ready"
    assert status["ready_for_discovery"] is False
    assert status["discovery_status"] == "empty"

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: client.nodes_list(
            args["space_id"],
            args.get("use_cache", True),
            args.get("force_refresh", False),
            args.get("cache_only", False),
        ),
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    resolved = await runtime.resolve_datasheet(table_name="客户表")

    assert resolved["error"]["code"] == "catalog_not_ready"
    assert resolved["error"]["details"]["catalog_status"]["discovery_status"] == status["discovery_status"]


@pytest.mark.anyio
async def test_folder_workbench_requires_space_id_without_global_space_scan() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    called = {"spaces": 0}
    registry.register(
        ToolDefinition(
            name="vika.spaces.list",
            description="List spaces.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain="connection",
            exposure="hidden",
        ),
        lambda args: called.__setitem__("spaces", called["spaces"] + 1) or {"spaces": [{"id": "spc1"}]},
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.resolve_datasheet(table_name="客户表")

    assert result["selected"] is None
    assert result["need_user_choice"] is True
    assert result["error"]["code"] == "workbench_space_id_required"
    assert called["spaces"] == 0


@pytest.mark.anyio
async def test_catalog_refresh_and_clear_are_not_model_entry_tools() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry())

    searched = await runtime.search_tools(query="refresh clear catalog cache", top_k=10)
    names = {candidate["name"] for candidate in searched["candidates"]}
    assert "vika.catalog.refresh" not in names
    assert "vika.catalog.clear" not in names

    for tool_name in ["vika.catalog.refresh", "vika.catalog.clear"]:
        described = await runtime.describe_tool(tool_name)
        called = await runtime.call_tool(tool_name, {})
        assert described["error"]["code"] == "tool_not_model_entry"
        assert called["error"]["code"] == "tool_not_model_entry"


@pytest.mark.anyio
async def test_live_space_and_node_tools_are_not_searchable_model_entries() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry())

    searched = await runtime.search_tools(query="space nodes list search tree get", top_k=10)
    names = {candidate["name"] for candidate in searched["candidates"]}
    assert "vika.spaces.list" not in names
    assert "vika.nodes.list" not in names
    assert "vika.nodes.search" not in names
    assert "vika.nodes.tree" not in names
    assert "vika.nodes.get" not in names

    for tool_name in ["vika.spaces.list", "vika.nodes.list", "vika.nodes.search", "vika.nodes.tree", "vika.nodes.get"]:
        described = await runtime.describe_tool(tool_name)
        called = await runtime.call_tool(tool_name, {})
        assert described["error"]["code"] == "tool_not_model_entry"
        assert called["error"]["code"] == "tool_not_model_entry"


@pytest.mark.anyio
async def test_meta_tool_search_excludes_read_all_model_entry() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry())
    result = await runtime.search_tools(query="export records", top_k=10)
    names = {candidate["name"] for candidate in result["candidates"]}

    assert "vika.records.read_all" not in names
    assert "vika_export_records" in names
    assert result["top_k"] <= 10


@pytest.mark.anyio
@pytest.mark.parametrize("workbench_url", [None, "https://vika.cn/workbench/fodRoot"])
@pytest.mark.parametrize(
    ("domain", "capability", "query", "expected_top"),
    [
        ("query", "records.query", None, "vika.records.query"),
        ("export", "records.export", None, "vika_export_records"),
        ("write", "records.create", None, "vika.records.create"),
        ("write", "records.update", None, "vika.records.update"),
        ("write", "records.delete", None, "vika.records.delete"),
        ("write", "write.commit", None, "vika.write.commit"),
        ("schema", "schema.get", None, "vika.schema.get"),
        ("schema", "fields.get", None, "vika.fields.get"),
        ("schema", "views.get", None, "vika.views.get"),
        (None, None, "records query", "vika.records.query"),
        (None, None, "导出记录", "vika_export_records"),
        (None, None, "提交写入", "vika.write.commit"),
    ],
)
async def test_meta_tool_search_is_capability_only(
    workbench_url: str | None,
    domain: str | None,
    capability: str | None,
    query: str | None,
    expected_top: str,
) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url=workbench_url)

    result = await runtime.search_tools(query=query or "", domain=domain, capability=capability, top_k=5)
    names = [candidate["name"] for candidate in result["candidates"]]

    assert names, (domain, capability, query)
    assert names[0] == expected_top
    assert all("subject_hint" not in candidate for candidate in result["candidates"])
    assert all("datasheet_query" not in candidate for candidate in result["candidates"])


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query",
    [
        "员工目录",
        "查询员工目录",
        "线下门店",
        "导出线下门店",
        "更新隐患记录",
    ],
)
async def test_meta_tool_search_does_not_parse_business_or_user_task_query(query: str) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.search_tools(query=query, top_k=5)

    assert result["candidates"] == []
    assert "guidance" in result
    assert "capability-only" in result["guidance"]
    assert "vika_resolve_datasheet" in result["guidance"]


@pytest.mark.anyio
async def test_meta_tool_search_capability_filter_is_primary_when_query_also_present() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry())

    result = await runtime.search_tools(query="records query", capability="records.update", top_k=5)
    names = [candidate["name"] for candidate in result["candidates"]]

    assert names == ["vika.records.update"]


@pytest.mark.anyio
async def test_guide_tells_llm_to_extract_business_subject_and_use_capability_search() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.guide()
    text = repr(result)

    assert "LLM" in text
    assert "业务表名" in text or "business table name" in text
    assert "capability-only" in text
    assert "structured workflow planner" in text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task_kind", "datasheet_query", "expected_tool", "expected_domain", "expected_capability"),
    [
        ("record_query", "员工目录", "vika.records.query", "query", "records.query"),
        ("record_export", "线下", "vika_export_records", "export", "records.export"),
        ("schema_read", "员工目录", "vika.schema.get", "schema", "schema.get"),
    ],
)
async def test_route_task_uses_structured_workflow_and_preserves_datasheet_query(
    task_kind: str,
    datasheet_query: str,
    expected_tool: str,
    expected_domain: str,
    expected_capability: str,
) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.route_task(task_kind=task_kind, datasheet_query=datasheet_query)

    assert result["task_kind"] == task_kind
    assert result["datasheet_query"] == datasheet_query
    assert "subject_hint" not in result
    assert result["recommended_sequence"][1] == f"vika_resolve_datasheet(query='{datasheet_query}')"
    assert result["recommended_sequence"][2] == f"vika_search_tools(domain='{expected_domain}', capability='{expected_capability}')"
    assert result["recommended_tools"][0]["tool_name"] == expected_tool


@pytest.mark.anyio
async def test_route_task_write_preview_flow_recommends_commit_without_autocommit() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.route_task(task_kind="record_update", datasheet_query="隐患记录")
    names = [item["tool_name"] for item in result["recommended_tools"]]

    assert result["datasheet_query"] == "隐患记录"
    assert names == ["vika.records.update", "vika.write.commit"]
    assert "user confirmation" in result["recommended_sequence"]
    assert result["auto_commits_write"] is False


@pytest.mark.anyio
async def test_route_task_rejects_legacy_free_text_task_input() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.route_task(task="查询员工目录")

    assert result["error"]["code"] == "unsupported_natural_language_route_input"

@pytest.mark.anyio
@pytest.mark.parametrize("task_kind", ["record_query", "record_export", "record_create", "record_update", "record_delete", "schema_read", "attachment_upload"])
async def test_route_task_requires_datasheet_target_for_table_workflows(task_kind: str) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.route_task(task_kind=task_kind)

    assert result["error"]["code"] == "datasheet_target_required"
    assert "datasheet_query" in result["error"]["details"]


@pytest.mark.anyio
async def test_route_task_write_commit_does_not_require_datasheet_target() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.route_task(task_kind="write_commit")
    names = [item["tool_name"] for item in result["recommended_tools"]]

    assert names == ["vika.write.commit"]
    assert "vika_resolve_datasheet" not in result["recommended_sequence"]
    assert result["auto_commits_write"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["搜索", "目录", "获取", "客户", "订单", "数据", "查询", "新增", "删除", "搜索目录", "获取目录项"])
async def test_search_does_not_admit_action_only_or_object_only_noise(query: str) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry(), workbench_url="https://vika.cn/workbench/fodRoot")

    result = await runtime.search_tools(query=query, top_k=5)

    assert result["candidates"] == []
    assert "guidance" in result


def test_record_tool_capabilities_do_not_depend_on_business_noun_enumeration() -> None:
    from vika_mcp.tools import vika_tools

    generic_record_tools = {
        "vika.records.query",
        "vika.records.get",
        "vika_export_records",
        "vika.records.create",
        "vika.records.update",
        "vika.records.delete",
    }
    forbidden_business_fragments = {"客户", "订单", "员工目录", "线下门店", "设备台账", "隐患记录", "巡检"}

    assert not hasattr(vika_tools, "TOOL_INTENTS")

    for tool_name in generic_record_tools:
        capability = vika_tools.TOOL_CAPABILITIES[tool_name]
        aliases = capability.get("aliases", [])
        assert not [
            alias
            for alias in aliases
            if any(fragment in alias for fragment in forbidden_business_fragments)
        ], tool_name

def test_cache_first_catalog_discovery_spec_disallows_stale_content_return() -> None:
    from pathlib import Path

    text = Path("docs/cache-first-catalog-discovery.md").read_text(encoding="utf-8")

    assert "return stale results" not in text
    assert "may return stale results" not in text
    assert "catalog_stale" in text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "required_fragments"),
    [
        ("vika.records.create", ["dstExample", "records", "Alice"]),
        ("vika.records.update", ["recExample", "records", "Alice"]),
        ("vika.records.delete", ["recExample", "record_ids"]),
        ("vika.write.commit", ["op_", "confirmed_payload_hash", "confirmed_by_user"]),
        ("vika.datasheets.create", ["spcExample", "fodExample", "客户跟进表"]),
        ("vika.records.query", ["dstExample", "page_size"]),
        ("vika_export_records", ["dstExample", "max_records", "csv"]),
    ],
)
async def test_describe_tool_returns_realistic_examples_for_llm_operation(
    tool_name: str,
    required_fragments: list[str],
) -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry())

    result = await runtime.describe_tool(tool_name)
    examples_text = repr(result["examples"])

    assert result["examples"], tool_name
    assert "_value" not in examples_text
    for fragment in required_fragments:
        assert fragment in examples_text


@pytest.mark.anyio
async def test_describe_tool_update_example_uses_recordId() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry())

    result = await runtime.describe_tool("vika.records.update")
    examples_text = repr(result["examples"])

    assert "recordId" in examples_text
    assert "record_id" not in examples_text


@pytest.mark.anyio
async def test_meta_artifact_tools_read_service_created_exports(tmp_path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    store = ArtifactStore(tmp_path)
    created = store.create_records_export(
        datasheet_id="dst123",
        records=[{"id": "rec1", "fields": {"name": "Alice"}}],
        field_names=["name"],
        source_args={"datasheet_id": "dst123"},
        format="jsonl",
    )
    runtime = MetaToolRuntime(build_hidden_registry(include_vika=False), artifact_store=store)

    head = await runtime.artifact_head(created["artifact_id"])
    search = await runtime.artifact_search(created["artifact_id"], "Alice")
    read = await runtime.artifact_read(created["artifact_id"], start_line=1, lines=1)
    status = await runtime.artifact_status(created["artifact_id"])

    assert head["returned_lines"] == 1
    assert search["hits"][0]["line_number"] == 1
    assert read["lines"][0].startswith('{"id":"rec1"')
    assert status["datasheet_id"] == "dst123"


@pytest.mark.anyio
async def test_workbench_scope_rejects_space_scoped_write_outside_configured_space() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="vika.datasheets.create",
            description="Create datasheet.",
            input_schema={
                "type": "object",
                "required": ["space_id", "name", "folder_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "name": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain="write",
            risk="medium",
            exposure="hidden",
            write=True,
            read_only=False,
        ),
        lambda args: {"executed": args},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                {"type": "node", "id": "fodChild", "parent_id": "fodRoot", "name": "child", "path": "root/child", "dst_id": None},
            ],
            "catalog": ready_discovery_catalog(),
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    wrong_space = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcOutside", "name": "outside", "folder_id": "fodRoot"},
    )
    assert wrong_space["error"]["code"] == "target_out_of_workbench_scope"

    wrong_folder = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "outside", "folder_id": "fodOutside"},
    )
    assert wrong_folder["error"]["code"] == "target_out_of_workbench_scope"


@pytest.mark.anyio
async def test_workbench_scope_rejects_writes_when_catalog_is_not_fresh() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    executed = {"called": False}
    registry.register(
        ToolDefinition(
            name="vika.datasheets.create",
            description="Create datasheet.",
            input_schema={
                "type": "object",
                "required": ["space_id", "name", "folder_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "name": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain="write",
            risk="medium",
            exposure="hidden",
            write=True,
            read_only=False,
        ),
        lambda args: executed.__setitem__("called", True) or {"executed": args},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "error": {
                "code": "catalog_stale",
                "message": "The cached space-node catalog is stale.",
                "details": {"catalog_status": "stale"},
            }
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    result = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodRoot"},
    )

    assert result["error"]["code"] == "catalog_stale"
    assert executed["called"] is False


@pytest.mark.anyio
async def test_workbench_scope_rejects_write_when_nodes_have_non_ready_catalog() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    executed = {"called": False}
    registry.register(
        ToolDefinition(
            name="vika.datasheets.create",
            description="Create datasheet.",
            input_schema={
                "type": "object",
                "required": ["space_id", "name", "folder_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "name": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain="write",
            risk="medium",
            exposure="hidden",
            write=True,
            read_only=False,
        ),
        lambda args: executed.__setitem__("called", True) or {"executed": args},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
            ],
            "catalog": {
                "readiness_type": "discovery",
                "readiness_status": "failed",
                "catalog_status": "failed",
                "ready_for_discovery": False,
                "last_refresh_error": "folder search failed",
            },
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    result = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodRoot"},
    )

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert executed["called"] is False


@pytest.mark.anyio
async def test_workbench_scope_rejects_write_with_inconsistent_ready_catalog_metadata() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    executed = {"called": False}
    registry.register(
        ToolDefinition(
            name="vika.datasheets.create",
            description="Create datasheet.",
            input_schema={
                "type": "object",
                "required": ["space_id", "name", "folder_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "name": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain="write",
            risk="medium",
            exposure="hidden",
            write=True,
            read_only=False,
        ),
        lambda args: executed.__setitem__("called", True) or {"executed": args},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
            ],
            "catalog": {
                "readiness_type": "discovery",
                "readiness_status": "ready",
                "discovery_status": "ready",
                "catalog_status": "failed",
                "ready_for_discovery": False,
                "last_refresh_error": "catalog metadata is inconsistent",
            },
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    result = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodRoot"},
    )

    assert result["error"]["code"] == "catalog_refresh_failed"
    assert executed["called"] is False


@pytest.mark.anyio
async def test_workbench_scope_retries_write_after_catalog_error_in_same_runtime() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    calls = {"nodes": 0}
    executed = {"called": 0}
    registry.register(
        ToolDefinition(
            name="vika.datasheets.create",
            description="Create datasheet.",
            input_schema={
                "type": "object",
                "required": ["space_id", "name", "folder_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "name": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain="write",
            risk="medium",
            exposure="hidden",
            write=True,
            read_only=False,
        ),
        lambda args: executed.__setitem__("called", executed["called"] + 1) or {"executed": args},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: (
            calls.__setitem__("nodes", calls["nodes"] + 1)
            or (
                {
                    "error": {
                        "code": "catalog_not_ready",
                        "message": "The workbench catalog is not ready.",
                    }
                }
                if calls["nodes"] == 1
                else {
                    "nodes": [
                        {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                    ],
                    "catalog": ready_discovery_catalog(),
                }
            )
        ),
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    first = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodRoot"},
    )
    second = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodRoot"},
    )

    assert first["error"]["code"] == "catalog_not_ready"
    assert second == {"executed": {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodRoot"}}
    assert calls["nodes"] == 2
    assert executed["called"] == 1


@pytest.mark.anyio
async def test_workbench_scope_recovers_after_write_failure_invalidates_previous_ready_cache() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    calls = {"nodes": 0}
    executed = {"called": 0}
    ready_nodes = [
        {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
        {"type": "datasheet", "id": "dst1", "parent_id": "fodRoot", "name": "客户表", "path": "root/客户表", "dst_id": "dst1"},
    ]
    registry.register(
        ToolDefinition(
            name="vika.datasheets.create",
            description="Create datasheet.",
            input_schema={
                "type": "object",
                "required": ["space_id", "name", "folder_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "name": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain="write",
            risk="medium",
            exposure="hidden",
            write=True,
            read_only=False,
        ),
        lambda args: executed.__setitem__("called", executed["called"] + 1) or {"executed": args},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: (
            calls.__setitem__("nodes", calls["nodes"] + 1)
            or (
                {"nodes": ready_nodes, "catalog": ready_discovery_catalog()}
                if calls["nodes"] in {1, 3}
                else {
                    "error": {
                        "code": "catalog_refresh_failed",
                        "message": "The last catalog refresh failed.",
                    }
                }
            )
        ),
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    first = await runtime.resolve_datasheet(table_name="客户表")
    failed_write = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodRoot"},
    )
    recovered = await runtime.resolve_datasheet(table_name="客户表")

    assert first["selected"]["datasheet_id"] == "dst1"
    assert failed_write["error"]["code"] == "catalog_refresh_failed"
    assert recovered["selected"]["datasheet_id"] == "dst1"
    assert calls["nodes"] == 3
    assert executed["called"] == 0


@pytest.mark.anyio
async def test_workbench_scope_allows_datasheet_create_only_under_scoped_folder() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="vika.datasheets.create",
            description="Create datasheet.",
            input_schema={
                "type": "object",
                "required": ["space_id", "name", "folder_id"],
                "properties": {
                    "space_id": {"type": "string"},
                    "name": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain="write",
            risk="medium",
            exposure="hidden",
            write=True,
            read_only=False,
        ),
        lambda args: {"executed": args},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                {"type": "node", "id": "fodChild", "parent_id": "fodRoot", "name": "child", "path": "root/child", "dst_id": None},
            ],
            "catalog": ready_discovery_catalog(),
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    allowed = await runtime.call_tool(
        "vika.datasheets.create",
        {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodChild"},
    )
    assert allowed == {"executed": {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodChild"}}


@pytest.mark.anyio
async def test_workbench_scope_rejects_node_tools_outside_configured_folder() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="vika.nodes.embedlinks.list",
            description="List embed links.",
            input_schema={
                "type": "object",
                "required": ["space_id", "node_id"],
                "properties": {"space_id": {"type": "string"}, "node_id": {"type": "string"}},
                "additionalProperties": False,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {"embed_links": []},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {
            "nodes": [
                {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                {"type": "node", "id": "fodChild", "parent_id": "fodRoot", "name": "child", "path": "root/child", "dst_id": None},
                {"type": "node", "id": "fodOutside", "parent_id": None, "name": "outside", "path": "outside", "dst_id": None},
            ],
            "catalog": ready_discovery_catalog(),
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    blocked = await runtime.call_tool("vika.nodes.embedlinks.list", {"space_id": "spcAllowed", "node_id": "fodOutside"})
    assert blocked["error"]["code"] == "target_out_of_workbench_scope"

    allowed = await runtime.call_tool("vika.nodes.embedlinks.list", {"space_id": "spcAllowed", "node_id": "fodChild"})
    assert allowed == {"embed_links": []}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("catalog_error_code", "message"),
    [
        ("catalog_refresh_failed", "The last catalog refresh failed."),
        ("catalog_stale", "The cached catalog is stale."),
    ],
)
async def test_workbench_scope_propagates_catalog_errors_for_read_only_node_scoped_tools(
    catalog_error_code: str,
    message: str,
) -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="vika.nodes.embedlinks.list",
            description="List embed links.",
            input_schema={
                "type": "object",
                "required": ["space_id", "node_id"],
                "properties": {"space_id": {"type": "string"}, "node_id": {"type": "string"}},
                "additionalProperties": False,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {"embed_links": []},
    )
    registry.register(
        ToolDefinition(
            name="vika.nodes.list",
            description="List nodes.",
            input_schema={
                "type": "object",
                "required": ["space_id"],
                "properties": {"space_id": {"type": "string"}},
                "additionalProperties": True,
            },
            domain="discovery",
            exposure="hidden",
        ),
        lambda args: {"error": {"code": catalog_error_code, "message": message}},
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    result = await runtime.call_tool("vika.nodes.embedlinks.list", {"space_id": "spcAllowed", "node_id": "fodChild"})

    assert result["error"]["code"] == catalog_error_code
    assert result["error"]["message"] == message
