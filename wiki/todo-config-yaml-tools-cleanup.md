---
title: 'Todo: clean up tools list comments in .dagi/config.yaml'
description: 'config.yaml says tools can be set to null (now a save error) and lists unregistered tools tmux_bash and enter_plan_mode.'
tags: [config.yaml, tools, tmux_bash, enter_plan_mode, settings_view]
updated: 2026-10-14
---
- The `tools:` comment says "Omit (or set to null) to enable all available tools" — the Settings tab refuses `tools: null`; change to "Omit".
- `tmux_bash` and `enter_plan_mode` are in the list but not registered by `create_tool_registry`; Settings shows them as "unknown". Remove or rename. No due date.
