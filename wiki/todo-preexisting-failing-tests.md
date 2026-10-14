---
title: 'Todo: fix tests failing on main (2026-10-14)'
description: 'Six tests fail on main independent of settings-tab: board viewer identity collision, 3 workflow plan template tests, notepad flush, paste cards clipboard.'
tags: [pytest, test_viewer, test_workflow_plan_template, test_desktop_pet_notepad, test_paste_cards, flaky]
updated: 2026-10-14
---
Verified failing on `main` (detached worktree) on 2026-10-14:
- `tests/message_board/test_viewer.py::test_identity_collision_retries_with_new_suffix` (`KeyError: 'posted'`)
- `tests/test_workflow_plan_template.py` — 3 tests
- `pyside_gui/tests/test_desktop_pet_notepad.py::test_edits_are_flushed_on_hide` ("editor did not load")
- `pyside_gui/tests/test_paste_cards.py::test_ctrl_shift_v_pastes_long_text_inline` ("OpenClipboard Failed" — likely environmental)
