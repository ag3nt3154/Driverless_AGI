---
title: 'Code mode: positional tool args map onto the stub order (required first)'
description: 'tools.<name>(...) in a code script accepts positional args; the parent maps them with param_order(schema), the same order the stub shows.'
tags: [code-mode, tools/code, param_order, tool_stub, posargs, _Tools, CodeTool, TypeError]
updated: 2026-10-12
---
Error before the fix (2026-10-11):

```
TypeError: _Tools.__getattr__.<locals>.<lambda>() takes 0 positional arguments but 1 was given
```

## Cause
The script-side proxy in `tools/code/_runner.py` was `lambda **args`. The script process has
no tool schemas, but the `code` tool description shows stubs like `tools.bash(command: str, ...)`,
so models call tools positionally.

## Fix
- The child sends positional values as an optional `"posargs"` list in the call message.
  Keyword-only calls send the same message as before.
- `CodeTool._dispatch` maps them with `param_order(schema)` (`tools/code/_stubs.py`):
  required parameters first, then optional ones, in schema `properties` order. `tool_stub`
  uses the same function, so the shown signature and the mapping cannot drift.
- Mapping happens before the call and the ledger entry. Too many values, or one parameter
  given both ways, raise `ToolError` and do not call the tool.

## Gotcha
The positional order is the **stub order**, not the tool's `run()` signature. If a tool's
schema `properties` order (or its `required` list) changes, positional calls in scripts
change meaning. At the fix date, all CODE_TOOLS schemas match their `run()` order.
