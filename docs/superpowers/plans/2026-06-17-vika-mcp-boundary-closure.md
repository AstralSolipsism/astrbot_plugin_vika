# Vika MCP Boundary Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the current Vika MCP architecture gaps so workbench scope, tool contracts, export artifacts, and write plans are governed by one coherent runtime boundary.

**Architecture:** The standard MCP server remains the only runtime entrypoint. Hidden Vika business tools stay behind meta tools, but all hidden calls must pass a centralized workbench scope guard and must use runtime-owned services instead of module globals or ad hoc store construction. Tool schemas must be executable contracts: a model following `vika_describe_tool` should not hit avoidable handler-level argument errors.

**Tech Stack:** Python 3.10+, MCP SDK `mcp==1.12.4`, Pydantic v2, pytest/anyio, `astral-vika` SDK, CSV-first tabular artifact files under `artifacts/exports/`; JSONL remains an optional machine-readable export format.

**Single Execution Source:** Coding agents must execute this document only: `docs/superpowers/plans/2026-06-17-vika-mcp-boundary-closure.md`. Other docs in `docs/` are product/user/reference docs that this plan may update; they are not competing implementation plans and must not override this document.

---

## 0. Execution Rules

This document is authoritative for the next development stage. Do not widen scope unless a verification step proves this plan incomplete.

- Architecture first: prefer one runtime boundary over compatibility, migration, or parallel mechanisms.
- No old `/mcp/v1/*` protocol restoration.
- No old `confirmed_summary` / `confirmation_summary` confirmation protocol.
- No token-wide discovery when `VIKAMCP_VIKA__WORKBENCH_URL` is configured.
- No unbounded export API call from a model-visible contract.
- No per-tool ad hoc `ArtifactStore()` or module-global `WritePlanStore` ownership after this stage.
- Tests must be written before implementation for each behavior change.
- Do not write Vika API tokens into docs, fixtures, tests, artifacts, or logs.

## 1. Decisions Already Fixed By This Plan

These are not open questions for the implementation agent.

1. **Workbench scope is a central runtime guard.**
   `MetaToolRuntime` must not own scattered scope checks inline. Create one scope component and route all hidden tool calls through it.

2. **Folder workbench scope is folder-bounded, not just space-bounded.**
   If the configured workbench URL is `fod...`, a target is in scope only when:
   - `space_id == VIKAMCP_VIKA__WORKBENCH_SPACE_ID`, and
   - `datasheet_id`, `node_id`, or `folder_id` is the root node or a descendant of that root.

3. **Datasheet workbench scope is single-datasheet bounded.**
   If the configured workbench URL is `dst...`, only that datasheet is in scope. Creating new datasheets and folder/node-level embedlink operations are blocked.

4. **`datasheets.create` remains available but only under the configured folder.**
   Under a folder workbench (`fod...`), `vika.datasheets.create` must require `folder_id`; the `folder_id` must be the configured folder root or a descendant. Creating at space root is out of scope.

5. **Node embedlink tools remain available but are node-scoped.**
   `vika.nodes.embedlinks.list/create/delete` must require `space_id == workbench_space_id` and `node_id` in the configured folder subtree. Under a single datasheet workbench, only `node_id == configured dst id` is allowed.

6. **Mixed `datasheet_id + space_id` tools must validate both.**
   `vika.fields.create/delete` must reject calls where `space_id` does not match the resolved datasheet's scoped space.

7. **Export is bounded.**
   `vika_export_records` must require `max_records`. `max_pages` may remain optional as an additional limiter, but `max_records` is the canonical model-facing bound.

8. **Export hard cap is 100000 records for this stage.**
   If `max_records > 100000`, validation must reject the call before hitting Vika. A future product decision can raise or lower this, but this stage must not ship an unbounded export.

9. **CSV is the default export artifact format.**
   `vika_export_records` defaults to `format="csv"` so an execution agent can use pandas, spreadsheet tools, or ordinary CSV readers without depending on MCP-specific JSONL parsing. `format="jsonl"` remains supported for machine-oriented workflows. MCP `artifact_head/search/read/status` must work for both text formats.

10. **XLSX is explicitly out of scope for this stage.**
   Do not add `openpyxl` or any XLSX writer dependency in this stage. Do not expose `format="xlsx"` in model-facing schemas or docs. CSV is the pandas-friendly spreadsheet format for this stage; JSONL remains the optional machine-readable format.

11. **Attachment download contract is canonicalized to URL input.**
   `vika.attachments.download` must require `url`. The `attachment` object path is removed from the model-facing schema for this stage to avoid `oneOf` ambiguity in the current validator.

12. **Runtime services are owned by the standard MCP runtime.**
    `ArtifactStore` and `WritePlanStore` are created once per runtime/server instance and injected into hidden tool handlers. Tools do not construct their own service stores.

13. **All write-capable tools must have `domain == "write"`.**
    The write flag, domain, annotations, and search routing must agree. A write tool classified as `discovery` is a contract bug.

14. **Commit remains the only execution path for writes.**
    Write tools only preview. `vika.write.commit` executes the stored operation after hash-bound user confirmation.

## 2. User Decisions Needed

There are no blocking user decisions for this stage. XLSX has been explicitly deferred and must not be implemented in this stage.

The following choices are fixed by safety and architecture principles:

- bounded export instead of unbounded full export;
- keep `datasheets.create` and embedlink tools but enforce workbench membership;
- use URL-only attachment download schema;
- remove runtime store globals instead of keeping compatibility shims.

If the user later wants different product behavior, handle it after this closure stage as a new explicit change.

## 3. Current Failure Map

The current code has these known gaps:

- `runtime/meta_tools.py::_scope_error()` checks only `datasheet_id`; tools that use `space_id`, `node_id`, or `folder_id` can bypass the configured folder scope.
- `tools/vika_tools.py::vika_export_records()` constructs `ArtifactStore()` directly, while visible artifact tools read from `MetaToolRuntime.artifact_store`.
- `tools/vika_tools.py` owns module-global `_WRITE_PLANS`, which makes write plan ownership global instead of server/runtime-scoped.
- `vika_export_records` schema requires only `datasheet_id`, but its handler rejects calls missing `max_records` and `max_pages`.
- Artifact export is currently JSONL-shaped, which is useful for MCP line-window reads but weaker for execution agents that need pandas or spreadsheet-style analysis. CSV must become the default artifact format.
- `vika.attachments.download` schema allows calls with neither `url` nor `attachment`, but its handler rejects them.
- `vika.nodes.embedlinks.create/delete` are write tools but currently classify as `discovery` because `_domain_for_tool()` checks `.nodes.` before `WRITE_TOOLS`.

## 4. Target File Responsibilities

- `runtime/scope.py`
  New workbench scope component. It parses the configured workbench URL, loads scoped nodes once, resolves datasheets, and checks hidden tool arguments.

- `runtime/services.py`
  New runtime service container. It owns `ArtifactStore` and `WritePlanStore` per runtime/server instance.

- `runtime/artifacts.py`
  Owns artifact file creation and bounded artifact reads. It must create CSV by default, support JSONL when requested, record the format in the manifest, and keep `artifact_head/search/read/status` working for supported text formats.

- `runtime/meta_tools.py`
  Delegates scope resolution/checking to `WorkbenchScope`. Delegates artifact tools to runtime services. No scattered target checks.

- `runtime/build_registry.py`
  Accepts `RuntimeServices` and passes them into Vika tool registration.

- `tools/vika_tools.py`
  Removes module-global `_WRITE_PLANS` usage and direct `ArtifactStore()` construction. Registers Vika tools through service-aware handlers. Fixes write domain classification and model-facing schemas.

- `runtime/validation.py`
  Adds JSON schema `maximum` support for integer/number values.

- `standard_server.py`
  Creates one `RuntimeServices` instance and passes it to both hidden registry and meta runtime.

- `tests/test_standard_mcp_surface.py`
  Adds workbench scope matrix and domain/metadata contract tests.

- `tests/test_limits_and_artifacts.py`
  Adds export contract, export hard cap, CSV artifact format, and shared artifact service tests.

- `tests/test_write_plans.py`
  Adds per-runtime write plan isolation tests after services are introduced.

- `docs/tool-guide.md`, `docs/artifacts.md`, `docs/write-safety.md`, `docs/standard-mcp-refactor-plan.md`
  Updates only if implementation changes model-facing behavior described there.

## 5. Implementation Tasks

### Task 1: Add Workbench Scope Contract Tests

**Files:**
- Modify: `tests/test_standard_mcp_surface.py`

- [ ] **Step 1: Add failing tests for space/node/folder scope bypass**

Append these tests to `tests/test_standard_mcp_surface.py`:

```python
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

    wrong_space = await runtime.call_tool("vika.datasheets.create", {"space_id": "spcOutside", "name": "outside", "folder_id": "fodRoot"})
    assert wrong_space["error"]["code"] == "target_out_of_workbench_scope"

    wrong_folder = await runtime.call_tool("vika.datasheets.create", {"space_id": "spcAllowed", "name": "outside", "folder_id": "fodOutside"})
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

    allowed = await runtime.call_tool("vika.datasheets.create", {"space_id": "spcAllowed", "name": "inside", "folder_id": "fodChild"})
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_standard_mcp_surface.py::test_workbench_scope_rejects_space_scoped_write_outside_configured_space tests/test_standard_mcp_surface.py::test_workbench_scope_allows_datasheet_create_only_under_scoped_folder tests/test_standard_mcp_surface.py::test_workbench_scope_rejects_node_tools_outside_configured_folder -q
```

Expected: fail because `MetaToolRuntime._scope_error()` currently returns `None` when `datasheet_id` is absent.

### Task 2: Implement Central Workbench Scope Guard

**Files:**
- Create: `runtime/scope.py`
- Modify: `runtime/meta_tools.py`
- Test: `tests/test_standard_mcp_surface.py`

- [ ] **Step 1: Create `runtime/scope.py`**

Add:

```python
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional


HiddenToolCaller = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]


WORKBENCH_BLOCKED_TOOLS = {
    "vika.spaces.list",
    "vika.nodes.list",
    "vika.nodes.search",
    "vika.nodes.tree",
    "vika.nodes.get",
    "vika.catalog.refresh",
    "vika.catalog.search",
    "vika.catalog.get",
    "vika.catalog.clear",
}


class WorkbenchScope:
    def __init__(
        self,
        workbench_url: Optional[str] = None,
        workbench_space_id: Optional[str] = None,
        hidden_caller: Optional[HiddenToolCaller] = None,
    ) -> None:
        self.workbench_url = workbench_url
        self.workbench_space_id = workbench_space_id
        self._hidden_caller = hidden_caller
        self._nodes_cache: Optional[List[Dict[str, Any]]] = None
        self._datasheets_cache: Optional[List[Dict[str, Any]]] = None
        self.resolved_datasheet_ids: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.workbench_url)

    def root_id(self) -> Optional[str]:
        match = re.search(r"\b((?:fod|dst)[a-zA-Z0-9]+)\b", self.workbench_url or "")
        return match.group(1) if match else None

    def extract_datasheet_id(self, value: str) -> Optional[str]:
        match = re.search(r"\b(dst[a-zA-Z0-9]+)\b", value or "")
        return match.group(1) if match else None

    async def resolve_datasheet(
        self,
        parsed_id: Optional[str],
        table_name: Optional[str],
        query: Optional[str],
        space_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        root_id = self.root_id()
        if root_id and root_id.startswith("fod") and not self.workbench_space_id:
            return self._scope_error_result(
                code="workbench_space_id_required",
                message="Folder workbench scope requires vika.workbench_space_id / VIKAMCP_VIKA__WORKBENCH_SPACE_ID; token-wide space scanning is disabled.",
                match_basis="workbench_space_id_missing",
                details={"workbench_scope": self.workbench_url},
            )

        datasheets = await self.load_datasheets()
        if parsed_id:
            selected = next((item for item in datasheets if item.get("datasheet_id") == parsed_id), None)
            if selected:
                self.resolved_datasheet_ids.add(parsed_id)
                return {
                    "selected": selected,
                    "candidates": [],
                    "need_user_choice": False,
                    "match_basis": "datasheet_id_in_workbench_scope",
                    "workbench_scope": self.workbench_url,
                    "next_actions": ["vika_search_tools(domain='schema')", "vika_describe_tool", "vika_call_tool"],
                }
            return self._scope_error_result(
                code="datasheet_out_of_workbench_scope",
                message="The requested datasheet is not under the configured workbench scope.",
                match_basis="datasheet_id_out_of_workbench_scope",
                details={"datasheet_id": parsed_id, "space_id": space_id},
            )

        needle = (table_name or query or "").strip().lower()
        candidates = datasheets
        if needle:
            candidates = [
                item
                for item in datasheets
                if needle in (item.get("name") or "").lower() or needle in (item.get("path") or "").lower()
            ]
        if len(candidates) == 1:
            selected = candidates[0]
            self.resolved_datasheet_ids.add(selected["datasheet_id"])
            return {
                "selected": selected,
                "candidates": [],
                "need_user_choice": False,
                "match_basis": "workbench_scoped_name_match" if needle else "workbench_scoped_single_candidate",
                "workbench_scope": self.workbench_url,
                "next_actions": ["vika_search_tools(domain='schema')", "vika_describe_tool", "vika_call_tool"],
            }
        return {
            "selected": None,
            "candidates": candidates[:10],
            "need_user_choice": True,
            "match_basis": "workbench_scoped_candidates",
            "workbench_scope": self.workbench_url,
            "next_actions": ["Ask the user to choose one candidate, then call vika_resolve_datasheet with its datasheet_id."],
        }

    async def check_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if tool_name in WORKBENCH_BLOCKED_TOOLS:
            return {
                "error": {
                    "code": "workbench_scope_required",
                    "message": "Token-wide space/node/catalog exploration is disabled; use vika_resolve_datasheet within the configured workbench scope.",
                    "details": {"tool_name": tool_name, "workbench_scope": self.workbench_url},
                }
            }

        datasheet_id = arguments.get("datasheet_id")
        if datasheet_id:
            datasheet_error = await self._check_datasheet_target(str(datasheet_id), arguments)
            if datasheet_error is not None:
                return datasheet_error

        if arguments.get("space_id"):
            space_error = self._check_space_target(str(arguments["space_id"]))
            if space_error is not None:
                return space_error

        if arguments.get("node_id"):
            node_error = await self._check_node_target(str(arguments["node_id"]))
            if node_error is not None:
                return node_error

        if tool_name == "vika.datasheets.create":
            folder_id = arguments.get("folder_id")
            if not folder_id:
                return self._target_error("folder_id is required when creating a datasheet inside a folder workbench scope.", {"tool_name": tool_name})
            folder_error = await self._check_node_target(str(folder_id))
            if folder_error is not None:
                return folder_error

        return None

    async def load_datasheets(self) -> List[Dict[str, Any]]:
        if self._datasheets_cache is not None:
            return self._datasheets_cache
        root_id = self.root_id()
        if not root_id:
            self._datasheets_cache = []
            return self._datasheets_cache
        if root_id.startswith("dst"):
            self._datasheets_cache = [
                {
                    "datasheet_id": root_id,
                    "space_id": self.workbench_space_id,
                    "name": None,
                    "path": root_id,
                    "parent_id": None,
                    "source": "workbench_scope",
                }
            ]
            return self._datasheets_cache

        nodes = await self.load_nodes()
        by_id = {node.get("id"): node for node in nodes if node.get("id")}
        scoped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for node in nodes:
            datasheet_id = node.get("dst_id") or (node.get("id") if str(node.get("id") or "").startswith("dst") else None)
            if not datasheet_id or datasheet_id in seen:
                continue
            if datasheet_id == root_id or self._is_descendant_of(node, root_id, by_id):
                seen.add(datasheet_id)
                scoped.append(
                    {
                        "datasheet_id": datasheet_id,
                        "space_id": self.workbench_space_id,
                        "name": node.get("name"),
                        "path": node.get("path"),
                        "parent_id": node.get("parent_id") or node.get("parentId"),
                        "source": "workbench_scope",
                    }
                )
        self._datasheets_cache = scoped
        return self._datasheets_cache

    async def load_nodes(self) -> List[Dict[str, Any]]:
        if self._nodes_cache is not None:
            return self._nodes_cache
        root_id = self.root_id()
        if not root_id or root_id.startswith("dst") or not self.workbench_space_id or self._hidden_caller is None:
            self._nodes_cache = []
            return self._nodes_cache
        result = await self._hidden_caller("vika.nodes.list", {"space_id": self.workbench_space_id, "use_cache": False, "force_refresh": True})
        self._nodes_cache = result.get("nodes", []) if isinstance(result, dict) else []
        return self._nodes_cache

    async def _check_datasheet_target(self, datasheet_id: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if datasheet_id not in self.resolved_datasheet_ids:
            return {
                "error": {
                    "code": "datasheet_not_resolved",
                    "message": "Call vika_resolve_datasheet first so the datasheet is bound to the configured workbench scope.",
                    "details": {"datasheet_id": datasheet_id, "workbench_scope": self.workbench_url},
                }
            }
        if arguments.get("space_id") and self.workbench_space_id and arguments.get("space_id") != self.workbench_space_id:
            return self._target_error("space_id does not match the configured workbench space.", {"datasheet_id": datasheet_id, "space_id": arguments.get("space_id")})
        return None

    def _check_space_target(self, space_id: str) -> Optional[Dict[str, Any]]:
        if self.workbench_space_id and space_id != self.workbench_space_id:
            return self._target_error("space_id is outside the configured workbench scope.", {"space_id": space_id, "workbench_space_id": self.workbench_space_id})
        return None

    async def _check_node_target(self, node_id: str) -> Optional[Dict[str, Any]]:
        root_id = self.root_id()
        if not root_id:
            return self._target_error("workbench root is not configured.", {"node_id": node_id})
        if root_id.startswith("dst"):
            if node_id == root_id:
                return None
            return self._target_error("node_id is outside the configured datasheet workbench scope.", {"node_id": node_id, "root_id": root_id})
        nodes = await self.load_nodes()
        by_id = {node.get("id"): node for node in nodes if node.get("id")}
        node = by_id.get(node_id)
        if node_id == root_id or (node and self._is_descendant_of(node, root_id, by_id)):
            return None
        return self._target_error("node_id or folder_id is outside the configured folder workbench scope.", {"node_id": node_id, "root_id": root_id})

    def _is_descendant_of(self, node: Dict[str, Any], root_id: str, by_id: Dict[str, Dict[str, Any]]) -> bool:
        current = node
        visited: set[str] = set()
        while current:
            current_id = current.get("id")
            if current_id == root_id:
                return True
            if current_id in visited:
                return False
            visited.add(current_id)
            parent_id = current.get("parent_id") or current.get("parentId")
            if parent_id == root_id:
                return True
            current = by_id.get(parent_id) or {}
        return False

    def _scope_error_result(self, code: str, message: str, match_basis: str, details: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "selected": None,
            "candidates": [],
            "need_user_choice": True,
            "match_basis": match_basis,
            "workbench_scope": self.workbench_url,
            "error": {"code": code, "message": message, "details": details},
            "next_actions": ["Choose a target inside the configured workbench scope."],
        }

    def _target_error(self, message: str, details: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "error": {
                "code": "target_out_of_workbench_scope",
                "message": message,
                "details": {**details, "workbench_scope": self.workbench_url},
            }
        }
```

- [ ] **Step 2: Wire `MetaToolRuntime` to `WorkbenchScope`**

In `runtime/meta_tools.py`:

- import `WorkbenchScope` and `WORKBENCH_BLOCKED_TOOLS` from `runtime.scope`;
- remove the local `WORKBENCH_BLOCKED_TOOLS`;
- create `self.scope = WorkbenchScope(workbench_url, workbench_space_id, self._call_hidden_raw)` in `__init__`;
- replace `self.resolved_datasheet_ids` and `_workbench_datasheets_cache` usage with `self.scope`;
- make `resolve_datasheet()` call `await self.scope.resolve_datasheet(...)`;
- make `_scope_error()` async or remove it and call `await self.scope.check_tool_call(tool_name, arguments or {})` from `call_tool()`.

The relevant `call_tool()` block must become:

```python
        scope_error = await self.scope.check_tool_call(tool_name, arguments or {})
        if scope_error is not None:
            return scope_error
        return await handler(arguments or {})
```

- [ ] **Step 3: Remove duplicated scope helpers from `runtime/meta_tools.py`**

Remove these methods after the new scope component is wired:

- `_extract_datasheet_id`
- `_extract_workbench_node_id`
- `_resolve_from_workbench_scope`
- `_load_workbench_datasheets`
- `_is_descendant_of`
- `_scope_error`

Keep `_call_hidden_raw()` because `WorkbenchScope` uses it through dependency injection.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest tests/test_standard_mcp_surface.py::test_workbench_scope_rejects_space_scoped_write_outside_configured_space tests/test_standard_mcp_surface.py::test_workbench_scope_allows_datasheet_create_only_under_scoped_folder tests/test_standard_mcp_surface.py::test_workbench_scope_rejects_node_tools_outside_configured_folder tests/test_standard_mcp_surface.py::test_resolve_datasheet_uses_workbench_folder_scope tests/test_standard_mcp_surface.py::test_folder_workbench_requires_space_id_without_global_space_scan -q
```

Expected: all selected tests pass.

### Task 3: Fix Tool Domains And Scope-Sensitive Schemas

**Files:**
- Modify: `tools/vika_tools.py`
- Modify: `runtime/validation.py`
- Test: `tests/test_standard_mcp_surface.py`, `tests/test_limits_and_artifacts.py`

- [ ] **Step 1: Add domain contract test**

Append to `tests/test_standard_mcp_surface.py`:

```python
def test_all_write_tools_are_in_write_domain() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    write_tools = [tool for tool in registry.list_hidden_tools(include_unavailable=True) if tool.write]

    assert write_tools
    assert {tool.name for tool in write_tools if tool.domain != "write"} == set()
```

- [ ] **Step 2: Add export and attachment schema tests**

Append to `tests/test_limits_and_artifacts.py`:

```python
def test_export_records_schema_requires_explicit_record_bound() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    spec, _handler = registry.get("vika_export_records")

    assert "max_records" in spec.input_schema["required"]
    assert spec.input_schema["properties"]["max_records"]["maximum"] == 100000
    assert spec.input_schema["properties"]["format"]["enum"] == ["csv", "jsonl"]


def test_attachment_download_schema_requires_url() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry

    registry = build_hidden_registry()
    spec, _handler = registry.get("vika.attachments.download")

    assert spec.input_schema["required"] == ["url"]
    assert "attachment" not in spec.input_schema["properties"]
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_standard_mcp_surface.py::test_all_write_tools_are_in_write_domain tests/test_limits_and_artifacts.py::test_export_records_schema_requires_explicit_record_bound tests/test_limits_and_artifacts.py::test_attachment_download_schema_requires_url -q
```

Expected: fail because embedlink write tools are classified as discovery, export does not require `max_records`, and attachment download still exposes ambiguous inputs.

- [ ] **Step 4: Fix `_domain_for_tool()` order**

In `tools/vika_tools.py`, make `WRITE_TOOLS` take precedence:

```python
def _domain_for_tool(name: str) -> str:
    if name in WRITE_TOOLS:
        return "write"
    if name in {"vika.status", "vika.healthcheck"}:
        return "connection"
    if ".catalog." in name or ".nodes." in name:
        return "discovery"
    if ".schema." in name or ".fields.get" in name or ".views.get" in name:
        return "schema"
    if ".records.query" in name or ".records.get" in name:
        return "query"
    if ".records.read_all" in name or name == "vika_export_records":
        return "export"
    return "admin"
```

- [ ] **Step 5: Add `maximum` validation support**

In `runtime/validation.py`, after the current `minimum` check, add:

```python
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{name} must be <= {schema['maximum']}")
```

- [ ] **Step 6: Fix export schema**

In `tools/vika_tools.py`, define:

```python
    export_max_records_prop = {"type": "integer", "minimum": 1, "maximum": 100000}
```

Use it in `vika_export_records` registration and make `max_records` required:

```python
    registered += _register(
        registry,
        "vika_export_records",
        "导出有界记录到服务端 CSV artifact，返回 artifact_id、manifest 和后续 artifact_search/read 操作。必须提供 max_records，硬上限 100000；format 缺省为 csv，可显式选择 jsonl。",
        vika_export_records,
        {
            "datasheet_id": str_prop,
            "view_id": str_prop,
            "formula": str_prop,
            "fields": fields_prop,
            "page_size": int_prop,
            "max_records": export_max_records_prop,
            "max_pages": int_prop,
            "sort": sort_prop,
            "field_key": field_key_prop,
            "format": {"type": "string", "enum": ["csv", "jsonl"]},
        },
        ["datasheet_id", "max_records"],
        ["vika", "records", "export"],
    )
```

- [ ] **Step 7: Fix attachment download schema and handler**

Change `vika_attachments_download()` to URL-only:

```python
async def vika_attachments_download(args: Dict[str, Any]) -> Any:
    assert _CLIENT is not None
    return _raise_if_error(await _CLIENT.attachments_download(args["url"], None, args.get("save_path")))
```

Change registration:

```python
    registered += _register(
        registry,
        "vika.attachments.download",
        "按附件 URL 下载附件到本地。",
        vika_attachments_download,
        {"url": str_prop, "save_path": str_prop},
        ["url"],
        ["vika", "attachments"],
    )
```

- [ ] **Step 8: Run focused tests**

Run:

```powershell
python -m pytest tests/test_standard_mcp_surface.py::test_all_write_tools_are_in_write_domain tests/test_limits_and_artifacts.py::test_export_records_schema_requires_explicit_record_bound tests/test_limits_and_artifacts.py::test_attachment_download_schema_requires_url -q
```

Expected: all selected tests pass.

### Task 4: Make CSV The Default Export Artifact Format

**Files:**
- Modify: `runtime/artifacts.py`
- Modify: `tools/vika_tools.py`
- Test: `tests/test_limits_and_artifacts.py`

- [ ] **Step 1: Add failing CSV artifact tests**

Append to `tests/test_limits_and_artifacts.py`:

```python
def test_artifact_store_writes_csv_by_default_for_tabular_analysis(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path)
    created = store.create_records_export(
        datasheet_id="dst123",
        records=[{"id": "rec1", "fields": {"name": "Alice", "score": 3}}],
        field_names=["name", "score"],
        source_args={"datasheet_id": "dst123", "max_records": 1},
    )

    assert created["format"] == "csv"
    assert created["path"].endswith(".csv")
    assert created["record_count"] == 1

    text = Path(created["path"]).read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "record_id,name,score"
    assert "rec1,Alice,3" in text

    head = store.head(created["artifact_id"], lines=2)
    assert head["lines"][0] == "record_id,name,score"
    assert head["returned_lines"] == 2


def test_artifact_store_can_still_write_jsonl_when_requested(tmp_path: Path) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path)
    created = store.create_records_export(
        datasheet_id="dst123",
        records=[{"id": "rec1", "fields": {"name": "Alice"}}],
        field_names=["name"],
        source_args={"datasheet_id": "dst123", "max_records": 1, "format": "jsonl"},
        format="jsonl",
    )

    assert created["format"] == "jsonl"
    assert created["path"].endswith(".jsonl")
    assert store.status(created["artifact_id"])["format"] == "jsonl"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_limits_and_artifacts.py::test_artifact_store_writes_csv_by_default_for_tabular_analysis tests/test_limits_and_artifacts.py::test_artifact_store_can_still_write_jsonl_when_requested -q
```

Expected: fail because `ArtifactStore.create_records_export()` does not exist and current artifact creation is JSONL-only.

- [ ] **Step 3: Implement `create_records_export()`**

In `runtime/artifacts.py`:

- import `csv`;
- add `ARTIFACT_SUPPORTED_FORMATS = {"csv", "jsonl"}`;
- replace direct callers of `create_jsonl_export()` with `create_records_export()`;
- do not keep `create_jsonl_export()` as a second public path unless an existing test still requires it. Development stage favors one canonical method.

The new method must have this signature:

```python
    def create_records_export(
        self,
        datasheet_id: str,
        records: Iterable[Dict[str, Any]],
        field_names: Optional[List[str]] = None,
        source_args: Optional[Dict[str, Any]] = None,
        space_id: Optional[str] = None,
        view_id: Optional[str] = None,
        query: Optional[Dict[str, Any]] = None,
        format: str = "csv",
    ) -> Dict[str, Any]:
```

CSV writing rules:

```python
        if format not in ARTIFACT_SUPPORTED_FORMATS:
            raise ValueError(f"unsupported artifact format: {format}")
        rows = list(records)
        columns = field_names or sorted({key for record in rows for key in (record.get("fields") or {}).keys()})
        if format == "csv":
            path = self._data_path(artifact_id, "csv")
            with path.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["record_id", *columns], extrasaction="ignore")
                writer.writeheader()
                for record in rows:
                    fields = record.get("fields") or {}
                    writer.writerow({"record_id": record.get("id"), **{column: fields.get(column) for column in columns}})
        else:
            path = self._data_path(artifact_id, "jsonl")
            with path.open("w", encoding="utf-8", newline="\n") as fh:
                for record in rows:
                    fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
```

The returned manifest must include:

```python
        manifest = {
            "artifact_id": artifact_id,
            "datasheet_id": datasheet_id,
            "space_id": space_id,
            "view_id": view_id,
            "query": query or {},
            "field_names": columns,
            "record_count": len(rows),
            "format": format,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_tool_args_hash": args_hash,
        }
```

- [ ] **Step 4: Make `head/search/read` use manifest format**

In `runtime/artifacts.py`, replace `_existing_jsonl_path()` use inside `head/search/read` with a format-aware helper:

```python
    def _existing_data_path(self, artifact_id: str) -> Path:
        manifest = self.status(artifact_id)
        fmt = manifest.get("format") or "csv"
        path = self._data_path(artifact_id, fmt)
        if not path.is_file():
            raise ValueError(f"artifact not found: {artifact_id}")
        return path
```

Add:

```python
    def _data_path(self, artifact_id: str, format: str) -> Path:
        self._validate_artifact_id(artifact_id)
        if format not in ARTIFACT_SUPPORTED_FORMATS:
            raise ValueError(f"unsupported artifact format: {format}")
        path = (self.root / f"{artifact_id}.{format}").resolve()
        self._ensure_inside_root(path)
        return path
```

- [ ] **Step 5: Update `vika_export_records()` to pass format**

In `tools/vika_tools.py`, export through runtime services after Task 5, but this task can prepare the handler call:

```python
    return services.artifact_store.create_records_export(
        datasheet_id=args["datasheet_id"],
        records=records,
        field_names=field_names,
        source_args=args,
        view_id=args.get("view_id"),
        query={"formula": args.get("formula"), "sort": args.get("sort")},
        format=args.get("format") or "csv",
    )
```

If Task 5 has not yet introduced `services`, use the same call shape when Task 5 edits the handler. Do not reintroduce direct `ArtifactStore()` construction.

- [ ] **Step 6: Run focused CSV artifact tests**

Run:

```powershell
python -m pytest tests/test_limits_and_artifacts.py::test_artifact_store_writes_csv_by_default_for_tabular_analysis tests/test_limits_and_artifacts.py::test_artifact_store_can_still_write_jsonl_when_requested -q
```

Expected: all selected tests pass.

### Task 5: Introduce Runtime Services And Remove Store Split

**Files:**
- Create: `runtime/services.py`
- Modify: `standard_server.py`
- Modify: `runtime/build_registry.py`
- Modify: `runtime/meta_tools.py`
- Modify: `tools/vika_tools.py`
- Test: `tests/test_limits_and_artifacts.py`, `tests/test_write_plans.py`

- [ ] **Step 1: Add service ownership tests**

Append to `tests/test_limits_and_artifacts.py`:

```python
@pytest.mark.anyio
async def test_export_records_uses_runtime_artifact_store(tmp_path, monkeypatch) -> None:
    from vika_mcp.runtime.artifacts import ArtifactStore
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.meta_tools import MetaToolRuntime
    from vika_mcp.runtime.services import RuntimeServices
    from vika_mcp.tools import vika_tools

    class FakeClient:
        configured = True

        async def records_read_all(self, *args, **kwargs):
            return {"records": [{"id": "rec1", "fields": {"name": "Alice"}}]}

    services = RuntimeServices(artifact_store=ArtifactStore(tmp_path))
    old_client = vika_tools._CLIENT
    vika_tools._CLIENT = FakeClient()
    try:
        registry = build_hidden_registry(services=services)
        runtime = MetaToolRuntime(registry, artifact_store=services.artifact_store)
        exported = await runtime.call_tool("vika_export_records", {"datasheet_id": "dst123", "max_records": 1})
        read = await runtime.artifact_read(exported["artifact_id"], start_line=1, lines=2)

        assert exported["format"] == "csv"
        assert exported["path"].endswith(".csv")
        assert read["returned_lines"] == 2
        assert read["lines"][0] == "record_id,name"
        assert read["lines"][1] == "rec1,Alice"
        assert str(tmp_path) in exported["path"]
    finally:
        vika_tools._CLIENT = old_client
```

Append to `tests/test_write_plans.py`:

```python
@pytest.mark.anyio
async def test_runtime_services_isolate_write_plan_stores() -> None:
    from vika_mcp.runtime.build_registry import build_hidden_registry
    from vika_mcp.runtime.services import RuntimeServices
    from vika_mcp.tools import vika_tools

    class FakeClient:
        configured = True

        async def records_create(self, datasheet_id, records, field_key=None):
            return {"datasheet_id": datasheet_id, "created": len(records)}

    old_client = vika_tools._CLIENT
    vika_tools._CLIENT = FakeClient()
    try:
        services_a = RuntimeServices()
        services_b = RuntimeServices()
        registry_a = build_hidden_registry(services=services_a)
        registry_b = build_hidden_registry(services=services_b)

        _spec_a, create_a = registry_a.get("vika.records.create")
        _spec_b, commit_b = registry_b.get("vika.write.commit")
        preview = await create_a({"datasheet_id": "dst123", "records": [{"fields": {"name": "Alice"}}]})
        rejected = await commit_b(
            {
                "operation_id": preview["operation_id"],
                "confirmed_payload_hash": preview["payload_hash"],
                "confirmed_by_user": True,
            }
        )

        assert rejected["error"]["code"] == "operation_not_found"
    finally:
        vika_tools._CLIENT = old_client
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_limits_and_artifacts.py::test_export_records_uses_runtime_artifact_store tests/test_write_plans.py::test_runtime_services_isolate_write_plan_stores -q
```

Expected: fail because `runtime.services` does not exist and tools still use module-global stores.

- [ ] **Step 3: Create `runtime/services.py`**

Add:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .artifacts import ArtifactStore
from .write_plans import WritePlanStore


@dataclass
class RuntimeServices:
    artifact_store: ArtifactStore = field(default_factory=ArtifactStore)
    write_plans: WritePlanStore = field(default_factory=WritePlanStore)
```

- [ ] **Step 4: Modify `runtime/build_registry.py`**

Replace the function with:

```python
from __future__ import annotations

from .registry import ToolRegistry
from .services import RuntimeServices
from ..tools import vika_tools


def build_hidden_registry(include_vika: bool = True, services: Optional[RuntimeServices] = None) -> ToolRegistry:
    registry = ToolRegistry()
    runtime_services = services or RuntimeServices()
    if include_vika:
        vika_tools.try_register_vika_tools(registry, services=runtime_services)
    return registry
```

Also import `Optional` from `typing`.

- [ ] **Step 5: Modify `standard_server.py`**

Create services once:

```python
    from .runtime.services import RuntimeServices

    services = RuntimeServices()
    hidden_registry = build_hidden_registry(services=services)
    runtime = MetaToolRuntime(
        hidden_registry,
        workbench_url=getattr(config.vika, "workbench_url", None),
        workbench_space_id=getattr(config.vika, "workbench_space_id", None),
        artifact_store=services.artifact_store,
    )
```

- [ ] **Step 6: Modify `tools/vika_tools.py` registration signatures**

Remove module-global `_WRITE_PLANS = WritePlanStore()`. Keep importing `WritePlanStore` only if directly needed by type hints; otherwise remove it.

Change `try_register_vika_tools` signature:

```python
def try_register_vika_tools(registry: ToolRegistry, services: Optional[RuntimeServices] = None) -> int:
```

Create local service:

```python
    runtime_services = services or RuntimeServices()
```

Pass `runtime_services` into `_register()`:

```python
    registered += _register(..., services=runtime_services)
```

Change `_register()` signature:

```python
def _register(
    registry: ToolRegistry,
    name: str,
    description: str,
    handler: Callable[[Dict[str, Any], RuntimeServices], Any],
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    available: Optional[bool] = None,
    output_schema: Optional[Dict[str, Any]] = None,
    services: Optional[RuntimeServices] = None,
) -> int:
```

Register a closure:

```python
    runtime_services = services or RuntimeServices()
    registry.register(spec, lambda args: handler(args, runtime_services))
```

- [ ] **Step 7: Modify write/export handlers to accept services**

Change handler signatures for export and write tools:

```python
async def vika_export_records(args: Dict[str, Any], services: RuntimeServices) -> Any:
```

Use:

```python
    return services.artifact_store.create_records_export(...)
```

Change all preview write handlers:

```python
async def vika_records_create(args: Dict[str, Any], services: RuntimeServices) -> Any:
```

Use:

```python
    return services.write_plans.preview(...)
```

Change commit:

```python
async def vika_write_commit(args: Dict[str, Any], services: RuntimeServices) -> Any:
    return await services.write_plans.commit(...)
```

For read-only handlers, either accept `services` and ignore it, or wrap them in `_register()` with an adapter. Use one uniform signature for all handlers in this stage to avoid branching.

- [ ] **Step 8: Run focused service tests**

Run:

```powershell
python -m pytest tests/test_limits_and_artifacts.py::test_export_records_uses_runtime_artifact_store tests/test_write_plans.py::test_runtime_services_isolate_write_plan_stores -q
```

Expected: all selected tests pass.

### Task 6: Add Registry Contract Matrix Tests

**Files:**
- Modify: `tests/test_standard_mcp_surface.py`

- [ ] **Step 1: Add contract matrix test**

Append:

```python
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
```

- [ ] **Step 2: Run matrix test**

Run:

```powershell
python -m pytest tests/test_standard_mcp_surface.py::test_hidden_tool_contract_matrix_has_no_known_drift_patterns -q
```

Expected: pass after Tasks 2-4.

### Task 7: Update Documentation To Match Closed Boundaries

**Files:**
- Modify: `docs/tool-guide.md`
- Modify: `docs/artifacts.md`
- Modify: `docs/write-safety.md`
- Modify: `docs/standard-mcp-refactor-plan.md`

- [ ] **Step 1: Update `docs/tool-guide.md`**

Ensure it states:

```markdown
- All hidden tools are still called through `vika_call_tool`.
- When workbench scope is configured, every hidden call is checked against that scope, including `datasheet_id`, `space_id`, `node_id`, and `folder_id`.
- `vika_export_records` requires `max_records`; use a filter/formula and bounded CSV export, then inspect with artifact tools or let an execution agent analyze the CSV with pandas.
- Write tools only preview; commit requires `operation_id`, `confirmed_payload_hash`, and `confirmed_by_user=true`.
```

- [ ] **Step 2: Update `docs/artifacts.md`**

Ensure it states:

```markdown
`vika_export_records` is bounded and requires `max_records`. The current hard cap is 100000 records per export.

The default export format is CSV so execution agents can analyze artifacts with pandas or spreadsheet tooling. JSONL remains available for machine-oriented workflows. XLSX is out of scope for this stage and must not be advertised.

Export and artifact read/search/head/status use the same runtime-owned `ArtifactStore`; hidden tools must not construct separate artifact stores.
```

- [ ] **Step 3: Update `docs/write-safety.md`**

Ensure it states:

```markdown
Write plans are runtime-scoped. A preview generated by one server/runtime instance cannot be committed through another instance.
```

- [ ] **Step 4: Update `docs/standard-mcp-refactor-plan.md`**

Patch the relevant sections so acceptance criteria include:

```markdown
- Workbench scope checks `datasheet_id`, `space_id`, `node_id`, and `folder_id`.
- All write tools have `domain=write`.
- Export requires `max_records`, has a hard cap of 100000, defaults to CSV, and records artifact format in the manifest.
- ArtifactStore and WritePlanStore are runtime-owned services.
```

- [ ] **Step 5: Run documentation drift scan**

Run:

```powershell
rg -n '\bdry_run\b|\bconfirm\b|exact confirmation summary|\bconfirmed_summary\b|\bconfirmation_summary\b|ArtifactStore\(\)' docs runtime tools README.md standard_server.py -S --glob '!docs/superpowers/plans/**'
```

Expected:

- no old confirmation protocol in runtime/tools/user docs;
- no `dry_run`/`confirm` write protocol in user-facing docs;
- no `ArtifactStore()` construction in `tools/vika_tools.py`.

### Task 8: Full Regression And MCP Smoke

**Files:**
- No source edits unless verification fails.

- [ ] **Step 1: Run full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run stdio MCP smoke**

Run from `D:\AboutDEV`:

```powershell
$env:PYTHONPATH='D:\AboutDEV'
@'
import asyncio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    env = os.environ.copy()
    env['PYTHONPATH'] = r'D:\AboutDEV'
    params = StdioServerParameters(command=sys.executable, args=['-m','vika_mcp','--transport','stdio'], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            guide = await session.call_tool('vika_guide', {})
            print({'tools_count': len(names), 'has_guide': 'vika_guide' in names, 'has_business': 'vika.records.query' in names, 'guide_blocks': len(guide.content)})
asyncio.run(main())
'@ | python -
```

Expected:

```text
{'tools_count': 12, 'has_guide': True, 'has_business': False, 'guide_blocks': 1}
```

- [ ] **Step 3: Run streamable-http MCP smoke**

Start server from `D:\AboutDEV`:

```powershell
$env:PYTHONPATH='D:\AboutDEV'
python -m vika_mcp --transport streamable-http --host 127.0.0.1 --port 18765
```

In another shell:

```powershell
$env:PYTHONPATH='D:\AboutDEV'
@'
import asyncio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with httpx.AsyncClient(trust_env=False) as http_client:
        async with streamable_http_client('http://127.0.0.1:18765/mcp', http_client=http_client) as (read, write, get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                guide = await session.call_tool('vika_guide', {})
                print({'tools_count': len(names), 'has_guide': 'vika_guide' in names, 'has_business': 'vika.records.query' in names, 'guide_blocks': len(guide.content), 'session_id_present': get_session_id() is not None})
asyncio.run(main())
'@ | python -
```

Expected:

```text
{'tools_count': 12, 'has_guide': True, 'has_business': False, 'guide_blocks': 1, 'session_id_present': True}
```

Stop the server with Ctrl+C. A `KeyboardInterrupt` traceback after shutdown is acceptable for this smoke.

- [ ] **Step 4: Run sensitive token scan**

Run:

```powershell
rg -n "Authorization: Bearer [A-Za-z0-9_-]+|VIKAMCP_VIKA__API_TOKEN\\s*=\\s*['\"]?[A-Za-z0-9_-]{12,}" . -S
```

Expected: no output.

## 6. Acceptance Criteria

This stage is complete only when all of these are true:

- `python -m pytest -q` passes.
- stdio smoke passes.
- streamable-http smoke passes.
- `vika_resolve_datasheet` still resolves only inside configured workbench scope.
- Hidden tool calls are checked for `datasheet_id`, `space_id`, `node_id`, and `folder_id` when workbench scope is configured.
- `vika.datasheets.create` cannot create outside the configured folder.
- `vika.nodes.embedlinks.*` cannot operate outside the configured folder or datasheet.
- `vika.fields.create/delete` reject mismatched `space_id`.
- All write-capable hidden tools have `domain == "write"`.
- `vika_export_records` requires `max_records` and rejects values above 100000 before API execution.
- `vika_export_records` defaults to CSV and writes a pandas-friendly `.csv` artifact.
- `format="jsonl"` remains supported for machine-oriented export when explicitly requested.
- XLSX is not present in the model-facing schema and is not implemented in this stage.
- `vika.attachments.download` requires `url`.
- Export uses the same runtime-owned `ArtifactStore` read by `vika_artifact_*`.
- Write preview/commit uses the same runtime-owned `WritePlanStore`.
- No `ArtifactStore()` construction remains in `tools/vika_tools.py`.
- No module-global `_WRITE_PLANS` remains in `tools/vika_tools.py`.
- No old confirmation protocol remains in implementation code.
- No Vika API token is written to repository files.

## 7. Non-Goals

- Do not restore FastAPI custom routes.
- Do not add `/mcp/v1/*` compatibility.
- Do not add a migration layer for old `dry_run/confirm`.
- Do not reintroduce `confirmation_summary` or `confirmed_summary`.
- Do not implement arbitrary local file reads through artifact tools.
- Do not make `vika.records.read_all` model-callable.
- Do not introduce dynamic MCP tool registration for domains.
- Do not add OAuth or non-static MCP auth in this stage.

## 8. Self-Review Checklist For The Implementation Agent

Before reporting completion:

- [ ] Re-read Sections 1, 6, and 7.
- [ ] Confirm every changed behavior has a failing test first.
- [ ] Confirm no task was skipped because another test happened to pass.
- [ ] Run the full test and smoke commands in Section 7.
- [ ] Run old protocol and token scans.
- [ ] Inspect `git diff --stat` and ensure edits are limited to files listed in Section 4 unless a test failure required a directly related change.
