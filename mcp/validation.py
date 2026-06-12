from typing import Any, Dict, List, Optional


class ToolInputInvalid(ValueError):
    """Raised when MCP tool arguments do not match the declared schema."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _type_matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_type_matches(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool))
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_value(name: str, value: Any, schema: Dict[str, Any], errors: List[str]) -> None:
    expected_type = schema.get("type")
    if expected_type is not None and not _type_matches(value, expected_type):
        errors.append(f"{name} must be of type {expected_type}")
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{name} must be one of {schema['enum']}")

    if isinstance(value, int) and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{name} must be >= {schema['minimum']}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{name} must contain at least {min_items} item(s)")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_value(f"{name}[{index}]", item, item_schema, errors)

    if isinstance(value, dict):
        validate_arguments(value, schema, prefix=name, errors=errors)


def validate_arguments(args: Dict[str, Any], schema: Optional[Dict[str, Any]], prefix: str = "", errors: Optional[List[str]] = None) -> List[str]:
    """Validate the small JSON-schema subset used by ToolSpec.input_schema."""
    collected = errors if errors is not None else []
    if not schema:
        return collected

    if schema.get("type") == "object" and not isinstance(args, dict):
        collected.append(f"{prefix or 'arguments'} must be an object")
        return collected

    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for key in required:
        if key not in args:
            collected.append(f"missing required argument: {key}")

    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in properties:
                collected.append(f"unexpected argument: {key}")

    for key, value in args.items():
        prop_schema = properties.get(key)
        if isinstance(prop_schema, dict):
            _validate_value(f"{prefix + '.' if prefix else ''}{key}", value, prop_schema, collected)

    return collected


__all__ = ["ToolInputInvalid", "validate_arguments"]
