---
title: 'Watching a file and its directory makes os.replace fail with WinError 5'
description: 'QFileSystemWatcher on both config.yaml and its parent dir caused ~3-4% of atomic saves to fail on Windows; watch only the file and retry os.replace.'
tags: [QFileSystemWatcher, os.replace, PermissionError, WinError 5, settings_view, config_editor, windows]
updated: 2026-10-14
---
```
Could not save: [WinError 5] Access is denied: '...config.yaml.tmp' -> '...config.yaml'
```

## Cause
`SettingsView` watched both `.dagi/config.yaml` and `.dagi/`. Writes to sibling files in the directory (e.g. `validate()`'s `.config.validate.*.yaml` temp file) woke Qt's Windows watcher thread, which briefly held the watched file open while `os.replace` ran. Probe: 17/460 saves failed with both watches; 0/250 file-only; 0/250 dir-only. Also made save tests flaky.

## Fix
- Watch only the file; add the parent directory only while the file is missing (to notice re-creation), remove it once the file is back. Re-add the file path after every save (`os.replace` drops it).
- `ConfigDocument.save` retries `os.replace` on `PermissionError` (5×, 50 ms) for antivirus/indexer locks.
