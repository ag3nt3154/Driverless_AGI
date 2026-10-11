"""tools/code/_stubs.py — Python-style signatures for the tools a script can call."""
from __future__ import annotations

_PY_TYPES = {
    "string": "str", "integer": "int", "number": "float", "boolean": "bool",
    "array": "list", "object": "dict",
}
BASH_RETURN = "dict  # {output: str, exit_code: int | None, timed_out: bool, killed: bool}"


def _param(name: str, prop: dict, optional: bool) -> str:
    text = f"{name}: {_PY_TYPES.get(prop.get('type'), 'object')}"
    return f"{text} = None" if optional else text


def param_order(schema: dict) -> list[str]:
    """Parameter names in stub order (required first); positional script args map onto it."""
    params = schema["function"].get("parameters", {})
    required = set(params.get("required", []))
    props = params.get("properties", {})
    return [n for n in props if n in required] + [n for n in props if n not in required]


def tool_stub(schema: dict) -> str:
    """``tools.read(path: str, offset: int = None) -> str`` from a provider tool schema."""
    fn = schema["function"]
    params = fn.get("parameters", {})
    required = set(params.get("required", []))
    props = params.get("properties", {})
    parts = [_param(n, props[n], n not in required) for n in param_order(schema)]
    returns = BASH_RETURN if fn["name"] == "bash" else "str"
    return f"tools.{fn['name']}({', '.join(parts)}) -> {returns}"
