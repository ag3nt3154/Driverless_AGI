---
name: build-api-tools
description: Ingest a Swagger/OpenAPI spec from .dagi/api_tools/ and generate callable BaseTool scripts in .dagi/tools/ — one per API endpoint
triggers: build api tools, generate api tools, ingest openapi spec, ingest swagger spec, generate tool from api, create api tools
---

# build-api-tools — Swagger Ingestion Workflow

## Purpose

This skill converts an OpenAPI 3.x specification into a set of runnable DAGI tools.
After ingestion, every API endpoint in the spec is individually discoverable via
`tool_search` and callable via `run_tool`.

**Where things live:**

| Path | Role |
|---|---|
| `.dagi/api_tools/` | Drop your swagger specs here (JSON or YAML) |
| `.dagi/tools/` | Generated BaseTool scripts land here |
| `scripts/build_api_tools.py` | The generator — run via bash |

---

## Step 1 — Confirm the spec is present

Use `find` to list files in `.dagi/api_tools/`:

```
find(".dagi/api_tools", "*.json")
find(".dagi/api_tools", "*.yaml")
find(".dagi/api_tools", "*.yml")
```

If no files are found, stop and tell the user:
> "Place your OpenAPI spec (JSON or YAML) in `.dagi/api_tools/` and then run this skill again."

If multiple specs are present, ask the user which one to ingest, or process all of them.

---

## Step 2 — Verify the output directory exists

Use `bash` to ensure `.dagi/tools/` exists:

```bash
mkdir -p .dagi/tools
```

---

## Step 3 — Run the generator

For each swagger file found in Step 1, run:

```bash
conda run -n dagi python scripts/build_api_tools.py \
    --swagger .dagi/api_tools/<filename> \
    --output-dir .dagi/tools
```

**Optional flags:**
- `--api-name MY_SERVICE` — sets the env-var prefix (e.g. `MY_SERVICE_API_KEY`).
  If omitted, the name is derived from the spec's `info.title`.

Read the output carefully:
- `wrote  get_pets.py  (GetPetsTool  →  tool: 'get-pets')` — a new tool was created
- `unchanged` — file already up to date
- Any `ERROR:` lines — address these before continuing

---

## Step 4 — Verify the generated files

Use `find` to confirm the tools were created:

```
find(".dagi/tools", "*.py")
```

Then spot-check one file with `read` to confirm it looks correct:
- It should import `BaseTool` and `requests`
- `name`, `description`, and `_parameters` should reflect the endpoint
- `_AUTH_ENV` and `_BASE_URL_ENV` should match the expected env-var prefix

---

## Step 5 — Check auth configuration

The generated tools read credentials from environment variables.
Tell the user which env vars to set:

```
{API_NAME}_API_KEY   — Bearer token / API key for authentication
{API_NAME}_BASE_URL  — Optional override for the base URL (uses spec's servers[0].url by default)
```

Suggest adding these to the project's `.env` file.

---

## Step 6 — Reload notice

**Generated tools are loaded at session start.**  The current session will NOT see
the new tools — the user must restart the DAGI session after ingestion.

Tell the user:
> "Tools have been generated. Restart this session to make them available.
> Then use `tool_search` to find and call them — e.g.:
> `tool_search('call the <API name> API to list X')`"

---

## Step 7 (optional) — Smoke-test a generated tool

If the API is publicly accessible (no auth required, or the user has set the env var):

1. Use `tool_search` to locate one of the generated tools
2. Call it via `run_tool` with minimal required args
3. Report the result back to the user

Example:
```
tool_search("list all pets from the petstore API")
→ MATCH: list-pets
run_tool(name="list-pets", args='{"limit": 5}')
```

---

## Edge Cases

**YAML specs require pyyaml:**
If the generator exits with `ERROR: pyyaml is required`, run:
```bash
conda run -n dagi pip install pyyaml
```
Then retry Step 3.

**Large specs (100+ endpoints):**
Generation may take a few seconds. This is normal — one file is written per endpoint.
The tool catalog scales fine because `tool_search` uses an LLM to match queries.

**Re-running after spec updates:**
The generator is idempotent — unchanged endpoints are skipped.
Endpoints that were removed from the spec will leave stale `.py` files in `.dagi/tools/`.
Remove them manually if needed:
```bash
ls .dagi/tools/
```

**Naming collisions:**
If two operations share the same `operationId`, the second write will overwrite the first.
This is a spec authoring error — flag it to the user.

**requests not installed:**
If a generated tool fails to load with `ModuleNotFoundError: requests`:
```bash
conda run -n dagi pip install requests
```
