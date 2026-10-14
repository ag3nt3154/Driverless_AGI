---
title: 'Bare config.yaml pattern in .gitignore hides test fixtures'
description: 'Any file named config.yaml is gitignored (.gitignore bare pattern), including tests/fixtures/*/config.yaml; force-add fixtures.'
tags: [gitignore, config.yaml, fixtures, git add -f, test_config_editor]
updated: 2026-10-14
---
`.gitignore` has a bare `config.yaml` pattern, so new files like `tests/fixtures/config_editor/config.yaml` don't appear in `git status`. Commit them with `git add -f <path>` (or add a `!` exception). Already-tracked files (`.dagi/config.yaml`) are unaffected.
