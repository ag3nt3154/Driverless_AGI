from __future__ import annotations

from pyside_gui.tests.test_conversation_reasoning import evaluate, view  # noqa: F401

_CARD = """
    const row = document.querySelector('.tool-call.compaction');
    return {
        label: row.querySelector('.tool-label').textContent,
        status: row.querySelector('.tool-status').textContent,
        failed: row.classList.contains('failed'),
        hidden: row.querySelector('.tool-detail').hidden,
        heading: row.querySelector('.compaction-summary h2')?.textContent ?? null,
        text: row.querySelector('.compaction-summary').textContent,
    };
"""


def test_compaction_is_a_collapsed_line_that_expands_to_the_summary(view):
    summary = (
        "[CONTEXT SUMMARY — conversation compacted (generation 3)]\n\n"
        "## Goal\nShip the compaction card."
    )
    view.append_compaction(4, 12, summary, False)
    card = evaluate(view, _CARD)
    assert card["label"] == "Context compacted — removed 12 steps, kept 4"
    assert card["status"] == "✓ gen 3"
    assert card["hidden"] is True and card["failed"] is False
    assert card["heading"] == "Goal"
    assert "CONTEXT SUMMARY" not in card["text"]

    opened = evaluate(view, """
        document.querySelector('.tool-call.compaction .tool-head').click();
        return document.querySelector('.tool-call.compaction .tool-detail').hidden;
    """)
    assert opened is False


def test_failed_compaction_shows_the_removal_notice(view):
    notice = "[CONTEXT REMOVED — earlier history was removed without a summary.]"
    view.append_compaction(1, 3, notice, True)
    card = evaluate(view, _CARD)
    assert card["failed"] is True
    assert card["status"] == "✕"
    assert "CONTEXT REMOVED" in card["text"]
