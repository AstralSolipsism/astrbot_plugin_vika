from __future__ import annotations

from typing import Optional

from .registry import ToolRegistry
from .services import RuntimeServices
from ..tools import vika_tools


def build_hidden_registry(include_vika: bool = True, services: Optional[RuntimeServices] = None) -> ToolRegistry:
    registry = ToolRegistry()
    runtime_services = services or RuntimeServices()
    if include_vika:
        vika_tools.try_register_vika_tools(registry, services=runtime_services)
    return registry
