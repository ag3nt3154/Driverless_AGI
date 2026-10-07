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


def tool_stub(schema: dict) -> str:
    """``tools.read(path: str, offset: int = None) -> str`` from a provider tool schema."""
    fn = schema["function"]
    params = fn.get("parameters", {})
    required = set(params.get("required", []))
    props = params.get("properties", {})
    parts = [_param(n, p, False) for n, p in props.items() if n in required]
    parts += [_param(n, p, True) for n, p in props.items() if n not in required]
    returns = BASH_RETURN if fn["name"] == "bash" else "str"
    return f"tools.{fn['name']}({', '.join(parts)}) -> {returns}"
