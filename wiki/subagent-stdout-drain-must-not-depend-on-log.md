---
title: 'Subagent stdout reader must drain independently of its log and decoder'
description: 'An idle pipe reader blocks a chatty child until timeout; drain into the tail even if the log or decoding fails, and note failures last.'
tags: [_tee_stdout, _subagent_runner, subprocess, pipe, UnicodeDecodeError, 'errors=replace', output_tail, R9, heredoc]
updated: 2026-10-05
---
Fixed 2026-10-05 (Codex review R9, commit 32107535) in `tools/_subagent_runner.py`.

## Cause
`_tee_stdout` opened the `.output.log` before reading and wrapped everything in
`except Exception: pass`; `Popen` decoded stdout as strict UTF-8. An unopenable log or one
invalid byte silently stopped the reader. Nothing drained the pipe, so a verbose child
blocked on `write()` once the OS pipe buffer filled — reproduced with ~1.6 MB of output and
an unopenable log: the run hit its timeout instead of exiting. Strict decoding also loses
the whole decoded chunk around a bad byte, not just its own line.

## Fix
- `Popen(..., errors="replace")`.
- Log open/write is best-effort (`_open_output_log`, `_write_output_log`): a failure stops
  logging, never draining.
- Failures become `[dagi] ...` notes appended to the tail in `finally`, after draining, and
  counted in `total_ref` — appending them first would let the 400-line ring buffer evict them.
- Tests drive the real `run_subagent` Popen kwargs against a `python -c` child
  (`TestStdoutDrainingSurvivesLoggingFailures`).

## Gotcha: test sources written via Git Bash heredoc
Writing the tests with `cat >> file <<'EOF'` collapsed `\\n` to `\n`, so the child sources
had `SyntaxError`s — hidden because the blocked log meant nobody read the child's error.
Write escape-heavy test code with Edit/Write and raw strings, and confirm a new test fails
for the intended reason, not merely that it fails.
