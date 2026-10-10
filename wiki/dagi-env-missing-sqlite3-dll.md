---
title: 'dagi env: _sqlite3 DLL load failure from a broken sqlite package'
description: 'The dagi env''s sqlite package was installed without Library/bin/sqlite3.dll; force-reinstall sqlite to restore it.'
tags: [sqlite3, _sqlite3, ImportError, 'sqlite3.dll', conda, dagi, message_board, TempBoard]
updated: 2026-10-10
---
```
ImportError: DLL load failed while importing _sqlite3: The specified module could not be found.
```

Every module importing `services.message_board.store` fails: board tests error at collection, and
the GUI's temp board (`sys.executable -m services.message_board serve ...`) exits at startup, so
the GUI cannot fall back when central is down.

## Cause
`conda list -n dagi sqlite` shows `sqlite 3.51.2` as installed, but
`envs/dagi/Library/bin/sqlite3.dll` is missing (only `DLLs/_sqlite3.pyd` is present). The
package files were partly lost; conda's metadata still records it as installed.

## Fix
```
conda install -y -n dagi --force-reinstall sqlite=3.51.2
C:\Users\alexr\miniconda3\envs\dagi\python.exe -c "import sqlite3; print(sqlite3.sqlite_version)"
```
Do not work around it with a DLL-search bootstrap pointing at another env (tried during the
board-app-split delivery; it hides the broken env from the real app).
