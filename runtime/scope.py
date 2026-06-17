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
        self._resolved_datasheets: Dict[str, Dict[str, Any]] = {}

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
            return self._resolve_error(
                code="workbench_space_id_required",
                match_basis="workbench_space_id_missing",
                message=(
                    "Folder workbench scope requires vika.workbench_space_id / "
                    "VIKAMCP_VIKA__WORKBENCH_SPACE_ID; token-wide space scanning is disabled."
                ),
                next_actions=[
                    "Configure VIKAMCP_VIKA__WORKBENCH_SPACE_ID for the workbench folder space, then retry vika_resolve_datasheet."
                ],
            )

        if space_id and self.workbench_space_id and space_id != self.workbench_space_id:
            return self._resolve_error(
                code="target_out_of_workbench_scope",
                match_basis="space_id_out_of_workbench_scope",
                message="The requested space_id is outside the configured workbench scope.",
                details={"space_id": space_id, "workbench_space_id": self.workbench_space_id},
            )

        datasheets = await self.load_datasheets()
        if parsed_id:
            selected = next((item for item in datasheets if item.get("datasheet_id") == parsed_id), None)
            if selected:
                self._remember_datasheet(selected)
                return {
                    "selected": selected,
                    "candidates": [],
                    "need_user_choice": False,
                    "match_basis": "datasheet_id_in_workbench_scope",
                    "workbench_scope": self.workbench_url,
                    "next_actions": ["vika_search_tools(domain='schema')", "vika_describe_tool", "vika_call_tool"],
                }
            return self._resolve_error(
                code="datasheet_out_of_workbench_scope",
                match_basis="datasheet_id_out_of_workbench_scope",
                message="The requested datasheet is not under the configured workbench scope.",
                next_actions=["Choose a datasheet returned by vika_resolve_datasheet within the configured workbench scope."],
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
            self._remember_datasheet(selected)
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
                    "message": (
                        "Token-wide space/node/catalog exploration is disabled; use vika_resolve_datasheet "
                        "within the configured workbench scope."
                    ),
                    "details": {"tool_name": tool_name, "workbench_scope": self.workbench_url},
                }
            }

        root_id = self.root_id()
        if root_id and root_id.startswith("fod") and not self.workbench_space_id:
            return self._scope_error(
                tool_name=tool_name,
                code="workbench_space_id_required",
                message=(
                    "Folder workbench scope requires vika.workbench_space_id / "
                    "VIKAMCP_VIKA__WORKBENCH_SPACE_ID; token-wide space scanning is disabled."
                ),
                match_basis="workbench_space_id_missing",
            )

        space_error = self._check_space_id(tool_name, arguments)
        if space_error is not None:
            return space_error

        if tool_name == "vika.datasheets.create":
            return await self._check_datasheet_create(tool_name, arguments)

        node_error = await self._check_node_targets(tool_name, arguments)
        if node_error is not None:
            return node_error

        datasheet_id = arguments.get("datasheet_id")
        if not datasheet_id:
            return None

        if datasheet_id not in self.resolved_datasheet_ids:
            return {
                "error": {
                    "code": "datasheet_not_resolved",
                    "message": "Call vika_resolve_datasheet first so the datasheet is bound to the configured workbench scope.",
                    "details": {"datasheet_id": datasheet_id, "workbench_scope": self.workbench_url},
                }
            }

        selected = self._resolved_datasheets.get(datasheet_id)
        selected_space = selected.get("space_id") if selected else None
        if selected_space and arguments.get("space_id") and arguments["space_id"] != selected_space:
            return self._target_out_error(
                tool_name,
                "space_id",
                arguments["space_id"],
                details={"datasheet_id": datasheet_id, "datasheet_space_id": selected_space},
            )
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

        if root_id.startswith("fod") and not self.workbench_space_id:
            self._datasheets_cache = []
            return self._datasheets_cache

        nodes = await self.load_nodes()
        by_id = self._nodes_by_id(nodes)
        scoped: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for node in nodes:
            datasheet_id = self._datasheet_id_for_node(node)
            if not datasheet_id or datasheet_id in seen:
                continue
            if datasheet_id == root_id or self._is_descendant_or_self(node, root_id, by_id):
                seen.add(datasheet_id)
                scoped.append(
                    {
                        "datasheet_id": datasheet_id,
                        "space_id": self.workbench_space_id or node.get("space_id"),
                        "name": node.get("name"),
                        "path": node.get("path") or node.get("name") or datasheet_id,
                        "parent_id": node.get("parent_id") or node.get("parentId"),
                        "source": "workbench_scope",
                    }
                )
        self._datasheets_cache = scoped
        return self._datasheets_cache

    async def load_nodes(self) -> List[Dict[str, Any]]:
        if self._nodes_cache is not None:
            return self._nodes_cache
        if not self._hidden_caller or not self.workbench_space_id:
            self._nodes_cache = []
            return self._nodes_cache
        result = await self._hidden_caller(
            "vika.nodes.list",
            {"space_id": self.workbench_space_id, "use_cache": False, "force_refresh": True},
        )
        nodes = result.get("nodes", []) if isinstance(result, dict) else []
        self._nodes_cache = nodes if isinstance(nodes, list) else []
        return self._nodes_cache

    def _remember_datasheet(self, selected: Dict[str, Any]) -> None:
        datasheet_id = selected.get("datasheet_id")
        if datasheet_id:
            self.resolved_datasheet_ids.add(datasheet_id)
            self._resolved_datasheets[datasheet_id] = selected

    def _check_space_id(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        space_id = arguments.get("space_id")
        if space_id and self.workbench_space_id and space_id != self.workbench_space_id:
            return self._target_out_error(
                tool_name,
                "space_id",
                space_id,
                details={"workbench_space_id": self.workbench_space_id},
            )
        return None

    async def _check_datasheet_create(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        root_id = self.root_id()
        if not root_id or root_id.startswith("dst"):
            return self._target_out_error(tool_name, "workbench_scope", root_id)

        folder_id = arguments.get("folder_id")
        if not folder_id:
            return self._target_out_error(tool_name, "folder_id", None)
        if await self._node_in_scope(folder_id):
            return None
        return self._target_out_error(tool_name, "folder_id", folder_id)

    async def _check_node_targets(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for key in ("node_id", "folder_id"):
            target_id = arguments.get(key)
            if target_id and not await self._node_in_scope(target_id):
                return self._target_out_error(tool_name, key, target_id)
        return None

    async def _node_in_scope(self, node_id: str) -> bool:
        root_id = self.root_id()
        if not root_id:
            return False
        if node_id == root_id:
            return True
        if root_id.startswith("dst"):
            return node_id == root_id
        nodes = await self.load_nodes()
        by_id = self._nodes_by_id(nodes)
        node = by_id.get(node_id)
        if not node:
            return False
        return self._is_descendant_or_self(node, root_id, by_id)

    def _nodes_by_id(self, nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {node.get("id"): node for node in nodes if node.get("id")}

    def _datasheet_id_for_node(self, node: Dict[str, Any]) -> Optional[str]:
        node_id = str(node.get("id") or "")
        dst_id = node.get("dst_id") or node.get("dstId")
        if dst_id:
            return str(dst_id)
        if node_id.startswith("dst"):
            return node_id
        return None

    def _is_descendant_or_self(self, node: Dict[str, Any], root_id: str, by_id: Dict[str, Dict[str, Any]]) -> bool:
        current = node
        visited: set[str] = set()
        while current:
            current_id = current.get("id")
            if current_id == root_id:
                return True
            if current_id in visited:
                return False
            if current_id:
                visited.add(current_id)
            parent_id = current.get("parent_id") or current.get("parentId")
            if parent_id == root_id:
                return True
            current = by_id.get(parent_id) or {}
        return False

    def _resolve_error(
        self,
        code: str,
        match_basis: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        next_actions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        return {
            "selected": None,
            "candidates": [],
            "need_user_choice": True,
            "match_basis": match_basis,
            "workbench_scope": self.workbench_url,
            "error": {
                "code": code,
                "message": message,
                "details": details or {"workbench_scope": self.workbench_url},
            },
            "next_actions": next_actions
            or ["Choose a target inside the configured workbench scope, then retry vika_resolve_datasheet."],
        }

    def _scope_error(self, tool_name: str, code: str, message: str, match_basis: str) -> Dict[str, Any]:
        return {
            "error": {
                "code": code,
                "message": message,
                "details": {
                    "tool_name": tool_name,
                    "match_basis": match_basis,
                    "workbench_scope": self.workbench_url,
                },
            }
        }

    def _target_out_error(
        self,
        tool_name: str,
        target_key: str,
        target_value: Any,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged_details = {
            "tool_name": tool_name,
            "target_key": target_key,
            "target_value": target_value,
            "workbench_scope": self.workbench_url,
        }
        if details:
            merged_details.update(details)
        return {
            "error": {
                "code": "target_out_of_workbench_scope",
                "message": "The requested target is outside the configured workbench scope.",
                "details": merged_details,
            }
        }
