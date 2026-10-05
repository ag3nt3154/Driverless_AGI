---
title: 'Tool registration order is the provider-visible schema order'
description: 'create_tool_registry order changes every request''s tool block and the prompt-cache prefix; update the ordered contract test deliberately when adding tools.'
tags: [create_tool_registry, ToolRegistry, get_openai_tools_list, prompt-cache, tool order, test_tool_registry_contract, R7]
updated: 2026-10-05
---
`ToolRegistry` stores tools in an insertion-ordered dict, and `get_openai_tools_list()`
emits schemas in that order. Reordering two `register` calls in `agent/tools.py` changes
the tool block of every request byte-for-byte and invalidates the warm prompt-cache
prefix, without any failing behaviour.

Since the 2026-10-05 R7 split, `create_tool_registry` delegates to phase helpers in a fixed
sequence: file tools → session tools → configured (subagents, extend_timeout, project,
skills, schedule) or fallback (web, skill) → filters → `write_handoff`.
`tests/test_tool_registry_contract.py` pins exact ordered name lists.

When adding a tool, choose its phase on purpose and update the expected lists in that test
in the same change. Never assert tool sets with `set()` in that file.
