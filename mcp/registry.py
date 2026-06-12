import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from .types import ToolSpec
from .validation import ToolInputInvalid, validate_arguments

HandlerType = Callable[[Dict[str, Any]], Union[Any, Awaitable[Any]]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
    
    def register(self, spec: ToolSpec, handler: HandlerType) -> None:
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
    
    def list_tools(self, include_unavailable: bool = False) -> List[ToolSpec]:
        tools: List[ToolSpec] = []
        for entry in self._tools.values():
            spec: ToolSpec = entry["spec"]
            if include_unavailable or spec.available:
                tools.append(spec)
        return tools
    
    def get(self, name: str) -> Tuple[ToolSpec, HandlerType]:
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        entry = self._tools[name]
        return entry["spec"], entry["handler"]
