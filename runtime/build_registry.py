from __future__ import annotations

from typing import Any, Optional

from ..config import load_config
from ..tools import builtin, vika_tools
from .registry import ToolRegistry
from .services import RuntimeServices


def _toolset_enabled(toolset: str, configured: bool, enabled_toolsets: set[str]) -> bool:
    if enabled_toolsets and toolset not in enabled_toolsets:
        return False
    return configured


def build_hidden_registry(
    include_vika: Optional[bool] = None,
    include_builtin: Optional[bool] = None,
    services: Optional[RuntimeServices] = None,
    config: Optional[Any] = None,
    vika_client: Optional[Any] = None,
) -> ToolRegistry:
    cfg = config or load_config()
    registry = ToolRegistry()
    runtime_services = services or RuntimeServices()

    configured_vika = cfg.registry.enable_vika_tools if include_vika is None else bool(include_vika)
    configured_builtin = cfg.registry.enable_builtin if include_builtin is None else bool(include_builtin)
    enabled_toolsets = {str(item).strip().lower() for item in (cfg.registry.enabled_toolsets or []) if str(item).strip()}

    if _toolset_enabled("builtin", configured_builtin, enabled_toolsets):
        builtin.register(registry)
    if _toolset_enabled("vika", configured_vika, enabled_toolsets):
        vika_tools.try_register_vika_tools(
            registry,
            services=runtime_services,
            config=cfg,
            client=vika_client,
        )
    return registry
