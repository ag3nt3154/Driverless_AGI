---
title: 'Settings tab edits .dagi/config.yaml through config_editor (comment-preserving)'
description: 'GUI Settings tab and save_config write config.yaml via agent/config_editor.py (ruamel round-trip); tools toggled by commenting lines; tools: null refused.'
tags: [settings_view, config_editor, ConfigDocument, ruamel.yaml, save_config, load_raw_config, disabled_tools, resolve_model_config, config.yaml]
updated: 2026-10-14
---
Decided 2026-10-13/14 (task `wiki/tasks/2026-10-14_settings-tab/`, merged `9b899db`).

## Decisions
- **Single writer:** `agent/config_editor.py` `ConfigDocument` (ruamel.yaml round-trip, `ruamel.yaml==0.19.1` in requirements-core) is the only code that writes `{DAGI_ROOT}/.dagi/config.yaml`. `save_config()` and `pyside_gui/sidebars/settings_view.py` both use it. Unedited round-trip is byte-identical; CRLF/LF preserved on save.
  - Rejected: `yaml.dump` (strips all comments); form-only or raw-only editors.
- **Scope:** root config only; changes apply to new sessions (no live reload).
- **Tools checklist:** unchecking comments the line out (`# - bash  # note`), re-checking uncomments in place, so annotations and section headers survive.
- **No `tools:` key** (= all tools): the form edits `disabled_tools` instead of writing a snapshot allowlist — a snapshot would silently drop project-local (`<project>/.dagi/tools`) and future tools, because `reg.filter_to` runs after they're registered.
- **Explicit `tools: null` is a save error:** ruamel renders null as bare `tools:`, indistinguishable from a fully commented list. For all tools, remove the key.
- **Save validates strictly** (`validate()`): typed scalars, model IDs in the catalog next to the file, `memory_root` exists, ≥1 enabled tool, board URL, then `resolve_model_config` on a temp copy in the same `.dagi/` dir. Unknown tool names and missing API keys are warnings only.

## Gotchas
- `load_raw_config()` merges `.dagi/model_config/*.yaml` into `raw["models"]` — never write its result back to config.yaml.
- `resolve_model_config` does **not** raise `EnvironmentError` for a missing API key (it only prints, despite its docstring); `validate()` has its own `_check_api_key` warning. Any exception from resolve (e.g. missing `client_script` → `FileNotFoundError`) is a real config error.
- Disabling every tool leaves `tools:` empty → `get("tools") is None` → loader treats it as ALL tools. Count enabled entries with `list_items("tools")`.
- `KNOWN_TOOL_NAMES` in `agent/tools.py` must track `create_tool_registry`; the drift test in `tests/test_tool_registry_contract.py` checks names and order.
