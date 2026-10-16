---
title: 'Configuration saves need serialized conflict checking and unique temporary files'
description: 'R28: concurrent ConfigDocument saves lose accepted edits or publish another writer''s bytes while returning their own hash.'
tags: [ConfigDocument, ConfigConflictError, config_editor, os.replace, concurrent-save, R28]
updated: 2026-10-16
---

Open at main `6b5b5a9534ce8fbd9af864b4d362cd6774bfc593`; no application repair was made.
The October 15 probes use scratch YAML and real ConfigDocument saves, with controlled
interleavings. They do not edit user configuration or exercise live GUI saves.

## Cause

`ConfigDocument.save` checks the target hash before publication and all writers use
`config.yaml.tmp`. No process ownership spans the final check, write and replace.
One accepted save can therefore be silently overwritten by a stale writer. With two
threads gated before replace, A published B's temporary bytes and returned A's hash;
B then raised:

```text
FileNotFoundError
```

A's returned hash differed from the saved file. All probe threads were released/joined.
This establishes an ordering defect, not its frequency in real use.

## Fix

Proposed: unique temporary files plus process-level writer serialization around the final
hash check, write and replace. Retain expected-hash conflicts inside that boundary and
clean up only the current writer's temporary file. Unique filenames alone leave the
stale-check lost update. Add controlled and independent-process regression coverage when
implementing. This proposal does not authorize implementation.

Evidence: [probe](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/config_save_probes.py),
[results](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/config_save_results.json).

## October 16 refresh

Both controlled interleavings reproduce at `a53f6eabe9d684b884ec14c98aab3f8312d4abac` after validation extraction;
ConfigDocument.save still shares the temporary filename and checks the hash before writing.
All scratch writer threads joined. [Results](C:/Users/alexr/.codex/visualizations/2026/10/16/01a144a3-a300-71c0-ae87-57f26f2608ca/config_save_results.json).
