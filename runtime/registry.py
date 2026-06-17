import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from .types import ToolDefinition
from .validation import ToolInputInvalid, validate_arguments

HandlerType = Callable[[Dict[str, Any]], Union[Any, Awaitable[Any]]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
    
    def register(self, spec: ToolDefinition, handler: HandlerType) -> None:
        """注册工具，如果同名则覆盖"""
        async def validated_handler(args: Dict[str, Any]) -> Any:
            errors = validate_arguments(args or {}, spec.input_schema)
            if errors:
                raise ToolInputInvalid(errors)
            result = handler(args or {})
            if inspect.isawaitable(result):
                return await result
            return result

        self._tools[spec.name] = {
            "spec": spec,
            "handler": validated_handler,
        }
    
    def list_tools(self, include_unavailable: bool = False, exposure: Optional[str] = None) -> List[ToolDefinition]:
        if exposure is not None and exposure not in {"visible", "hidden"}:
            raise ValueError(f"unknown tool exposure: {exposure}")

        tools: List[ToolDefinition] = []
        for entry in self._tools.values():
            spec: ToolDefinition = entry["spec"]
            if exposure is not None and spec.exposure != exposure:
                continue
            if include_unavailable or spec.available:
                tools.append(spec)
        return tools
    
    def list_visible_tools(self, include_unavailable: bool = False) -> List[ToolDefinition]:
        return self.list_tools(include_unavailable=include_unavailable, exposure="visible")

    def list_hidden_tools(self, include_unavailable: bool = False) -> List[ToolDefinition]:
        return self.list_tools(include_unavailable=include_unavailable, exposure="hidden")

    def get(self, name: str) -> Tuple[ToolDefinition, HandlerType]:
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        entry = self._tools[name]
        return entry["spec"], entry["handler"]
