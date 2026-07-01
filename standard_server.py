from __future__ import annotations

import os
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import AuthSettings
from mcp.types import ToolAnnotations

from .config import load_config
from .runtime.auth import StaticBearerTokenVerifier
from .runtime.build_registry import build_hidden_registry
from .runtime.meta_tools import MetaToolRuntime, visible_meta_tool_definitions
from .runtime.services import RuntimeServices
from .runtime.types import ToolDefinition


def _annotations_for(definition: ToolDefinition) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=definition.read_only,
        destructiveHint=definition.destructive,
        idempotentHint=not definition.write,
        openWorldHint=False,
    )


def create_standard_mcp(
    host: Optional[str] = None,
    port: Optional[int] = None,
    log_level: Optional[str] = None,
    transport: str = "stdio",
) -> FastMCP:
    config = load_config()
    services = RuntimeServices()
    hidden_registry = build_hidden_registry(services=services)
    runtime = MetaToolRuntime(
        hidden_registry,
        workbench_url=getattr(config.vika, "workbench_url", None),
        workbench_space_id=getattr(config.vika, "workbench_space_id", None),
        artifact_store=services.artifact_store,
    )
    effective_host = host or config.server.host or "127.0.0.1"
    effective_port = port or config.server.port or 8080
    auth_settings, token_verifier = _transport_auth(effective_host, effective_port, transport)
    server = FastMCP(
        "vika_mcp",
        instructions=(
            "Use vika_guide first when unsure. LLM extracts the business table name or business object from the "
            "user request and passes it unchanged to vika_resolve_datasheet(query=...). vika_search_tools is "
            "capability-only; use domain/capability such as records.query, records.export, schema.get, or "
            "records.update, not user business phrases. vika_route_task is a structured workflow planner: provide "
            "task_kind plus datasheet_query or datasheet_id, and do not pass free-text user tasks. Resolve "
            "datasheets before schema/query; discovery is cache-only and must not trigger catalog refresh or live "
            "space/node enumeration. Catalog content is returned only after the unified discovery/selector "
            "readiness gate is ready; empty, stale, refreshing, refresh_abandoned, failed, or disabled readiness "
            "means ask for maintenance instead. Use export/artifact tools for large reads. Writes must preview "
            "first; use confirmation_context/confirmation_brief as the factual source for one-sentence user "
            "confirmation, then commit with operation_id, confirmed_payload_hash, and confirmed_by_user=true."
        ),
        host=effective_host,
        port=effective_port,
        log_level=(log_level or config.server.log_level or "INFO").upper(),
        streamable_http_path="/mcp",
        json_response=True,
        auth=auth_settings,
        token_verifier=token_verifier,
    )
    register_meta_tools(server, runtime)
    return server


def _transport_auth(host: str, port: int, transport: str) -> tuple[AuthSettings | None, StaticBearerTokenVerifier | None]:
    if (transport or "stdio").replace("_", "-") != "streamable-http":
        return None, None

    token = os.getenv("VIKAMCP_MCP_BEARER_TOKEN")
    if not token:
        if _is_local_host(host):
            return None, None
        raise RuntimeError("streamable_http bound to a non-localhost address requires VIKAMCP_MCP_BEARER_TOKEN")

    base_url = f"http://{host}:{port}"
    return (
        AuthSettings(issuer_url=base_url, resource_server_url=base_url),
        StaticBearerTokenVerifier(token),
    )


def _is_local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def register_meta_tools(server: FastMCP, runtime: MetaToolRuntime) -> None:
    definitions = {definition.name: definition for definition in visible_meta_tool_definitions()}

    @server.tool(
        name="vika_guide",
        description=definitions["vika_guide"].description,
        annotations=_annotations_for(definitions["vika_guide"]),
    )
    async def vika_guide() -> Dict[str, Any]:
        return await runtime.guide()

    @server.tool(
        name="vika_resolve_datasheet",
        description=definitions["vika_resolve_datasheet"].description,
        annotations=_annotations_for(definitions["vika_resolve_datasheet"]),
    )
    async def vika_resolve_datasheet(
        datasheet_id: Optional[str] = None,
        url: Optional[str] = None,
        table_name: Optional[str] = None,
        space_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await runtime.resolve_datasheet(datasheet_id=datasheet_id, url=url, table_name=table_name, space_id=space_id, query=query)

    @server.tool(
        name="vika_search_tools",
        description=definitions["vika_search_tools"].description,
        annotations=_annotations_for(definitions["vika_search_tools"]),
    )
    async def vika_search_tools(
        query: str = "",
        domain: Optional[str] = None,
        capability: Optional[str] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        return await runtime.search_tools(query=query, domain=domain, capability=capability, top_k=top_k)

    @server.tool(
        name="vika_route_task",
        description=definitions["vika_route_task"].description,
        annotations=_annotations_for(definitions["vika_route_task"]),
    )
    async def vika_route_task(
        task_kind: str,
        datasheet_query: Optional[str] = None,
        datasheet_id: Optional[str] = None,
        has_user_confirmation: bool = False,
    ) -> Dict[str, Any]:
        return await runtime.route_task(
            task_kind=task_kind,
            datasheet_query=datasheet_query,
            datasheet_id=datasheet_id,
            has_user_confirmation=has_user_confirmation,
        )

    @server.tool(
        name="vika_describe_tool",
        description=definitions["vika_describe_tool"].description,
        annotations=_annotations_for(definitions["vika_describe_tool"]),
    )
    async def vika_describe_tool(tool_name: str) -> Dict[str, Any]:
        return await runtime.describe_tool(tool_name)

    @server.tool(
        name="vika_call_tool",
        description=definitions["vika_call_tool"].description,
        annotations=_annotations_for(definitions["vika_call_tool"]),
    )
    async def vika_call_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        return await runtime.call_tool(tool_name, arguments)

    @server.tool(
        name="vika_list_domains",
        description=definitions["vika_list_domains"].description,
        annotations=_annotations_for(definitions["vika_list_domains"]),
    )
    async def vika_list_domains() -> Dict[str, Any]:
        return await runtime.list_domains()

    @server.tool(
        name="vika_activate_domain",
        description=definitions["vika_activate_domain"].description,
        annotations=_annotations_for(definitions["vika_activate_domain"]),
    )
    async def vika_activate_domain(domain: str) -> Dict[str, Any]:
        return await runtime.activate_domain(domain)

    @server.tool(
        name="vika_artifact_head",
        description=definitions["vika_artifact_head"].description,
        annotations=_annotations_for(definitions["vika_artifact_head"]),
    )
    async def vika_artifact_head(artifact_id: str, lines: int = 20) -> Dict[str, Any]:
        return await runtime.artifact_head(artifact_id, lines=lines)

    @server.tool(
        name="vika_artifact_search",
        description=definitions["vika_artifact_search"].description,
        annotations=_annotations_for(definitions["vika_artifact_search"]),
    )
    async def vika_artifact_search(artifact_id: str, query: str, max_hits: int = 20) -> Dict[str, Any]:
        return await runtime.artifact_search(artifact_id, query=query, max_hits=max_hits)

    @server.tool(
        name="vika_artifact_read",
        description=definitions["vika_artifact_read"].description,
        annotations=_annotations_for(definitions["vika_artifact_read"]),
    )
    async def vika_artifact_read(artifact_id: str, start_line: int = 1, lines: int = 100) -> Dict[str, Any]:
        return await runtime.artifact_read(artifact_id, start_line=start_line, lines=lines)

    @server.tool(
        name="vika_artifact_status",
        description=definitions["vika_artifact_status"].description,
        annotations=_annotations_for(definitions["vika_artifact_status"]),
    )
    async def vika_artifact_status(artifact_id: str, include_manifest: bool = True) -> Dict[str, Any]:
        return await runtime.artifact_status(artifact_id, include_manifest=include_manifest)
