---
title: 'Todo: fix tests failing on main (2026-10-14)'
description: 'October 14 recorded six failures; October 15 reproduced three plan-template failures, viewer collision passed, and notepad/clipboard were not rerun.'
tags: [pytest, test_viewer, test_workflow_plan_template, test_desktop_pet_notepad, test_paste_cards, flaky]
updated: 2026-10-15
---
Verified failing on `main` (detached worktree) on 2026-10-14:
- `tests/message_board/test_viewer.py::test_identity_collision_retries_with_new_suffix` (`KeyError: 'posted'`)
- `tests/test_workflow_plan_template.py` — 3 tests
- `pyside_gui/tests/test_desktop_pet_notepad.py::test_edits_are_flushed_on_hide` ("editor did not load")
- `pyside_gui/tests/test_paste_cards.py::test_ctrl_shift_v_pastes_long_text_inline` ("OpenClipboard Failed" — likely environmental)

October 15 focused rerun at `6b5b5a95`: the three plan-template failures still reproduce;
the viewer identity-collision test passed. Its earlier failure is not reproduced today,
and one pass does not establish a repaired cause. The notepad/clipboard tests were not
selected. Core selection: 263 passed, 3 failed, 2 skipped; separate offscreen Qt Settings/
sidebar/mentions/agents/board-controller selection: 131 passed. See the October 15 review
for exact scope and evidence; these counts are not a full-suite result.
