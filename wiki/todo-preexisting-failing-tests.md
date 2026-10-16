---
title: 'Todo: fix tests failing on main (2026-10-14)'
description: 'Plan-template failures repaired and verified October 16; historical viewer/notepad/clipboard observations retain their original scope.'
tags: [pytest, test_viewer, test_workflow_plan_template, test_desktop_pet_notepad, test_paste_cards, flaky]
updated: 2026-10-16
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

## October 16 refresh

Current writer-example contract tests now pass; the three obsolete-template failures are
resolved by 530fcd93. R15 is removed from the open report. This run did not select the viewer
collision, notepad or clipboard tests. Focused core selection: 328 passed, four sandbox-only
board/socket failures; exactly those four passed outside the sandbox. Separate Qt selection:
139 passed. These results do not establish closure of unselected historical UI failures.
