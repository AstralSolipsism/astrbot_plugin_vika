from __future__ import annotations

import pytest


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


def test_cli_accepts_standard_mcp_transport_options() -> None:
    from vika_mcp.__main__ import parse_args

    args = parse_args(["--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8080"])

    assert args.transport == "streamable-http"
    assert args.listen_host == "127.0.0.1"
    assert args.listen_port == 8080


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
            ]
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    blocked = await runtime.call_tool("hidden.schema", {"datasheet_id": "dstBlocked"})
    assert blocked["error"]["code"] == "datasheet_not_resolved"

    await runtime.resolve_datasheet(datasheet_id="dstAllowed")
    allowed = await runtime.call_tool("hidden.schema", {"datasheet_id": "dstAllowed"})
    assert allowed == {"datasheet_id": "dstAllowed"}


@pytest.mark.anyio
async def test_workbench_scope_blocks_token_wide_discovery_tools() -> None:
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

    assert result["error"]["code"] == "workbench_scope_required"


@pytest.mark.anyio
async def test_resolve_datasheet_uses_workbench_folder_scope() -> None:
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.registry import ToolRegistry
    from vika_mcp.runtime.types import ToolDefinition

    registry = ToolRegistry()
    called = {"spaces": 0, "nodes": 0}
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
            or {
                "nodes": [
                    {"type": "node", "id": "fodRoot", "parent_id": None, "name": "root", "path": "root", "dst_id": None},
                    {"type": "datasheet", "id": "dstInScope", "parent_id": "fodRoot", "name": "客户表", "path": "root/客户表", "dst_id": "dstInScope"},
                    {"type": "datasheet", "id": "dstOutside", "parent_id": "fodOther", "name": "外部表", "path": "other/外部表", "dst_id": "dstOutside"},
                ]
            }
        ),
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spc1")

    resolved = await runtime.resolve_datasheet(table_name="客户表")
    assert resolved["selected"]["datasheet_id"] == "dstInScope"
    assert resolved["need_user_choice"] is False
    assert called["spaces"] == 0
    assert called["nodes"] == 1

    rejected = await runtime.resolve_datasheet(datasheet_id="dstOutside")
    assert rejected["selected"] is None
    assert rejected["need_user_choice"] is True
    assert rejected["error"]["code"] == "datasheet_out_of_workbench_scope"


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
async def test_meta_tool_search_excludes_read_all_model_entry() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime

    runtime = MetaToolRuntime(build_hidden_registry())
    result = await runtime.search_tools(query="全量 批量读取", top_k=10)
    names = {candidate["name"] for candidate in result["candidates"]}

    assert "vika.records.read_all" not in names
    assert "vika_export_records" in names
    assert result["top_k"] <= 10


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
            ]
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
            ]
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
            ]
        },
    )
    runtime = MetaToolRuntime(registry, workbench_url="https://vika.cn/workbench/fodRoot", workbench_space_id="spcAllowed")

    blocked = await runtime.call_tool("vika.nodes.embedlinks.list", {"space_id": "spcAllowed", "node_id": "fodOutside"})
    assert blocked["error"]["code"] == "target_out_of_workbench_scope"

    allowed = await runtime.call_tool("vika.nodes.embedlinks.list", {"space_id": "spcAllowed", "node_id": "fodChild"})
    assert allowed == {"embed_links": []}
