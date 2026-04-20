#!/usr/bin/env python3
"""
scripts/build_api_tools.py — Generate DAGI BaseTool files from an OpenAPI spec.

Each path+method pair in the spec becomes a standalone Python file containing
a BaseTool subclass.  Generated files are placed in .dagi/tools/ and are
automatically discovered by create_tool_registry() on the next session start.

Usage:
    conda run -n dagi python scripts/build_api_tools.py \\
        --swagger  .dagi/api_tools/petstore.json \\
        --output-dir .dagi/tools \\
        --api-name PETSTORE

Arguments:
    --swagger     Path to the OpenAPI 3.x spec (JSON or YAML).
    --output-dir  Directory to write generated tool files.
                  Defaults to .dagi/tools relative to the current working dir.
    --api-name    Prefix used for env-var names, e.g. PETSTORE → PETSTORE_API_KEY.
                  Derived from info.title when omitted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows so Unicode characters in print() don't crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

def _load_spec(swagger_path: Path) -> dict:
    """Load an OpenAPI 3.x spec from a JSON or YAML file."""
    text = swagger_path.read_text(encoding="utf-8")
    if swagger_path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
            return yaml.safe_load(text)
        except ImportError:
            print(
                "ERROR: pyyaml is required for YAML specs.\n"
                "Install it with:  conda run -n dagi pip install pyyaml\n"
                "Or convert your spec to JSON with an online tool and re-run.",
                file=sys.stderr,
            )
            sys.exit(1)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert a URL path segment to a Python-safe lowercase slug.

    /pets/{petId}/photos  →  pets_petid_photos
    """
    slug = re.sub(r"[{}]", "", text)              # strip braces
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", slug)   # non-alphanum → _
    return slug.strip("_").lower() or "root"


def _to_pascal(text: str) -> str:
    """Convert snake_case, kebab-case or camelCase to PascalCase."""
    # Split on underscores, hyphens, or transitions between lower→upper
    tokens = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return "".join(w.capitalize() for w in re.split(r"[_\-]+", tokens))


def _to_snake(text: str) -> str:
    """Convert camelCase or PascalCase to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _to_kebab(text: str) -> str:
    """Convert any casing to kebab-case."""
    return _to_snake(text).replace("_", "-")


def _derive_api_name(spec: dict) -> str:
    """Derive an uppercase API name from spec info.title (e.g. 'Pet Store' → 'PET_STORE')."""
    title = spec.get("info", {}).get("title", "API")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", title).upper().strip("_")
    return cleaned or "API"


def _get_base_url(spec: dict) -> str:
    """Return the first server URL, stripping trailing slash and variable placeholders."""
    servers = spec.get("servers", [])
    if servers:
        url = servers[0].get("url", "")
        url = re.sub(r"\{[^}]+\}", "", url)   # remove server vars
        return url.rstrip("/")
    return ""


# ---------------------------------------------------------------------------
# Parameter / schema extraction
# ---------------------------------------------------------------------------

def _openapi_type_to_jsonschema(p_schema: dict) -> dict:
    """Convert a minimal OpenAPI param schema to a JSON Schema property dict."""
    out: dict = {}
    t = p_schema.get("type")
    if t:
        out["type"] = t
    fmt = p_schema.get("format")
    if fmt:
        out["format"] = fmt
    if "enum" in p_schema:
        out["enum"] = p_schema["enum"]
    return out or {"type": "string"}


def _build_schema(
    parameters: list[dict],
    request_body: dict | None,
) -> tuple[dict, list[str], list[str], bool]:
    """Extract JSON Schema + param lists from OpenAPI parameters and requestBody.

    Returns:
        schema       — JSON Schema object for the tool's _parameters field
        path_params  — list of path parameter names
        query_params — list of query parameter names
        has_body     — True if the operation accepts a request body
    """
    props: dict = {}
    required: list[str] = []
    path_params: list[str] = []
    query_params: list[str] = []
    has_body = False

    for p in parameters:
        location = p.get("in")
        if location not in ("path", "query"):
            continue
        name = p["name"]
        p_schema = p.get("schema", {})
        prop: dict = _openapi_type_to_jsonschema(p_schema)
        desc = p.get("description", "")
        if desc:
            prop["description"] = desc
        props[name] = prop

        if location == "path":
            path_params.append(name)
            required.append(name)          # path params are always required
        else:  # query
            query_params.append(name)
            if p.get("required"):
                required.append(name)

    if request_body:
        has_body = True
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        body_schema = json_content.get("schema", {})
        body_prop: dict = {"type": "object"}
        desc = request_body.get("description", "Request body (JSON object).")
        if desc:
            body_prop["description"] = desc
        if "properties" in body_schema:
            body_prop["properties"] = body_schema["properties"]
        props["body"] = body_prop
        if request_body.get("required"):
            required.append("body")

    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required

    return schema, path_params, query_params, has_body


def _example_args(schema: dict) -> str:
    """Build a minimal valid JSON example string from a JSON Schema."""
    props = schema.get("properties", {})
    req = set(schema.get("required", []))
    example: dict = {}
    for k, v in props.items():
        if k not in req:
            continue
        t = v.get("type", "string")
        if t == "integer":
            example[k] = 0
        elif t == "boolean":
            example[k] = True
        elif t == "object":
            example[k] = {}
        elif t == "array":
            example[k] = []
        else:
            example[k] = "..."
    return json.dumps(example)


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

def _sanitise_description(text: str) -> str:
    """Make a string safe for use inside a Python double-quoted string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").strip()


def _render_tool(
    *,
    swagger_path: str,
    operation_id: str,
    class_name: str,
    tool_name: str,
    description: str,
    http_method: str,
    path: str,
    parameters_schema: dict,
    path_params: list[str],
    query_params: list[str],
    has_body: bool,
    api_name: str,
    base_url: str,
) -> str:
    """Return the complete Python source for a generated BaseTool file."""

    # Serialise the JSON Schema as a Python dict literal (via json.dumps).
    # json.dumps produces valid Python for all types we use (str/int/bool/list/dict).
    schema_json = json.dumps(parameters_schema, indent=8)
    # Align with the 4-space class body indent.
    schema_indented = schema_json.replace("\n", "\n    ")

    path_params_repr = repr(path_params)
    query_params_repr = repr(query_params)
    desc_safe = _sanitise_description(description)

    # Build the source line-by-line.
    # We use regular strings (not f-strings) for lines that contain Python
    # braces, f-strings, or dict comprehensions — to avoid brace-escaping hell.
    lines: list[str] = []

    # ----- File header -----
    lines += [
        "# Auto-generated by build_api_tools.py  —  DO NOT EDIT",
        f"# Source: {swagger_path}  |  Operation: {operation_id}",
        "import json",
        "import os",
        "",
        "import requests",
        "",
        "from agent.base_tool import BaseTool",
        "",
        "",
        f"class {class_name}(BaseTool):",
        f'    name = "{tool_name}"',
        f'    description = "{desc_safe}"',
        f"    _parameters = {schema_indented}",
        "",
        f'    _BASE_URL = "{base_url}"',
        f'    _AUTH_ENV = "{api_name}_API_KEY"',
        f'    _BASE_URL_ENV = "{api_name}_BASE_URL"',
        "",
        "    def run(self, **kwargs) -> str:",
    ]

    # ----- Auth + headers (no f-string conflicts here) -----
    lines += [
        '        base_url = os.environ.get(self._BASE_URL_ENV, self._BASE_URL).rstrip("/")',
        '        token = os.environ.get(self._AUTH_ENV, "")',
        '        headers = {"Content-Type": "application/json"}',
        "        if token:",
        '            headers["Authorization"] = "Bearer " + token',
        "",
    ]

    # ----- Path parameter substitution -----
    lines += [
        "        # Substitute path parameters",
        f"        _path_params = {path_params_repr}",
        f'        path = "{path}"',
        "        for _p in _path_params:",
        '            path = path.replace("{" + _p + "}", str(kwargs.pop(_p, "")))',
        "",
    ]

    # ----- Query parameters -----
    lines += [
        "        # Collect query parameters",
        f"        _query_params = {query_params_repr}",
        "        params = {k: kwargs.pop(k) for k in _query_params if k in kwargs}",
        "",
    ]

    # ----- Request body -----
    lines += [
        "        # Request body",
        f'        body = kwargs.get("body") if {has_body} else None',
        "",
    ]

    # ----- HTTP call + error handling -----
    lines += [
        "        try:",
        f"            resp = requests.{http_method}(",
        "                base_url + path,",
        "                headers=headers,",
        "                params=params,",
        "                json=body,",
        "                timeout=30,",
        "            )",
        "            resp.raise_for_status()",
        "            try:",
        "                return json.dumps(resp.json(), indent=2)",
        "            except ValueError:",
        "                return resp.text",
        "        except requests.HTTPError as exc:",
        "            body_preview = exc.response.text[:500] if exc.response is not None else ''",
        "            return f\"HTTP {exc.response.status_code}: {body_preview}\"",
        "        except requests.RequestException as exc:",
        '            return f"Request failed: {exc}"',
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def generate(
    swagger_path: Path,
    output_dir: Path,
    api_name: str | None,
) -> int:
    """Parse *swagger_path* and write tool files into *output_dir*.

    Returns the number of files written (new or updated).
    """
    print(f"Loading spec: {swagger_path}")
    spec = _load_spec(swagger_path)

    resolved_api_name = api_name or _derive_api_name(spec)
    base_url = _get_base_url(spec)
    paths: dict = spec.get("paths", {})

    if not paths:
        print("WARNING: No paths found in spec — nothing to generate.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    for api_path, path_item in paths.items():
        # Resolve shared parameters at path level
        shared_params: list[dict] = path_item.get("parameters", [])

        for method in HTTP_METHODS:
            operation: dict | None = path_item.get(method)
            if not operation:
                continue

            # Merge shared params with operation-level params
            op_params: list[dict] = operation.get("parameters", [])
            # Operation-level params override shared ones with the same name+in
            seen = {(p["name"], p.get("in")): p for p in shared_params}
            seen.update({(p["name"], p.get("in")): p for p in op_params})
            merged_params = list(seen.values())

            request_body = operation.get("requestBody")

            # --- Naming ---
            op_id: str = operation.get("operationId") or ""
            path_slug = _slugify(api_path)
            base_stem = _to_snake(op_id) if op_id else f"{method}_{path_slug}"

            file_name = f"{base_stem}.py"
            class_name = _to_pascal(base_stem) + "Tool"
            tool_name = _to_kebab(base_stem)

            # Description: prefer summary, then operationId, then method+path
            summary = (
                operation.get("summary")
                or operation.get("description", "")
                or op_id
                or f"{method.upper()} {api_path}"
            )
            description = f"{method.upper()} {api_path} \u2014 {summary}"

            # --- Schema ---
            schema, path_params, query_params, has_body = _build_schema(
                merged_params, request_body
            )

            # --- Render ---
            source = _render_tool(
                swagger_path=str(swagger_path),
                operation_id=op_id or f"{method}:{api_path}",
                class_name=class_name,
                tool_name=tool_name,
                description=description,
                http_method=method,
                path=api_path,
                parameters_schema=schema,
                path_params=path_params,
                query_params=query_params,
                has_body=has_body,
                api_name=resolved_api_name,
                base_url=base_url,
            )

            out_file = output_dir / file_name

            # Idempotent: skip write if content unchanged
            if out_file.exists() and out_file.read_text(encoding="utf-8") == source:
                skipped += 1
                continue

            out_file.write_text(source, encoding="utf-8")
            written += 1
            print(f"  wrote  {out_file.name}  ({class_name} -> tool: {tool_name!r})")

    total = written + skipped
    print(
        f"\nDone. {total} tool(s) from {len(paths)} path(s) — "
        f"{written} written, {skipped} unchanged."
    )
    print(f"Output: {output_dir.resolve()}")
    print(
        "\nTools become available on the next DAGI session start.\n"
        f"Auth env vars:  {resolved_api_name}_API_KEY  /  {resolved_api_name}_BASE_URL"
    )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate DAGI BaseTool files from an OpenAPI spec.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--swagger",
        required=True,
        type=Path,
        help="Path to the OpenAPI 3.x spec (JSON or YAML).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write generated tool files (default: .dagi/tools).",
    )
    parser.add_argument(
        "--api-name",
        type=str,
        default=None,
        help=(
            "Uppercase prefix for env-var names, e.g. PETSTORE → PETSTORE_API_KEY. "
            "Derived from info.title when omitted."
        ),
    )
    args = parser.parse_args()

    swagger_path: Path = args.swagger.resolve()
    if not swagger_path.exists():
        print(f"ERROR: swagger file not found: {swagger_path}", file=sys.stderr)
        sys.exit(1)

    output_dir: Path = (
        args.output_dir.resolve()
        if args.output_dir
        else (Path.cwd() / ".dagi" / "tools")
    )

    generate(swagger_path, output_dir, args.api_name)


if __name__ == "__main__":
    main()
