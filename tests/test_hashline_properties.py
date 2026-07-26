"""Invariants the hashline design depends on.

These guard the three properties that make anchors safe: uniqueness within a
file, agreement across tools, and order-independence of batched edits.
"""
import random
from pathlib import Path

from tools import _hashline as H
from tools.edit import EditTool

_REPO = Path(__file__).resolve().parent.parent


class TestUniqueness:
    def test_anchors_unique_across_repo_source_files(self):
        sources = sorted((_REPO / "tools").rglob("*.py"))
        assert sources, "expected to find repo source files"
        for path in sources:
            lines = path.read_text(encoding="utf-8").splitlines()
            anchors = H.build_anchors(lines)
            assert len(set(anchors)) == len(anchors), f"duplicate anchor in {path}"

    def test_anchors_unique_on_pathological_input(self):
        lines = ["}"] * 500 + [""] * 500
        anchors = H.build_anchors(lines)
        assert len(set(anchors)) == 1000


class TestCrossToolAgreement:
    def test_read_and_grep_agree_with_edit(self, tmp_path):
        from tools.grep import GrepTool
        from tools.read import ReadTool

        lines = ["import os", "import os", "needle", "import os"]
        (tmp_path / "f.py").write_text("\n".join(lines), encoding="utf-8", newline="\n")

        read_line = [
            ln for ln in ReadTool(cwd=tmp_path, allowed_roots=[tmp_path])
            .run(path="f.py").splitlines() if "needle" in ln
        ][0]
        grep_line = [
            ln for ln in GrepTool(cwd=tmp_path, allowed_roots=[tmp_path])
            .run(pattern="needle").splitlines() if "needle" in ln
        ][0]

        read_anchor = read_line.split(":", 1)[0].strip()
        grep_anchor = grep_line.split(":", 2)[1].strip()

        assert read_anchor == grep_anchor

        result = EditTool(cwd=tmp_path, allowed_roots=[tmp_path]).run(
            path="f.py",
            edits=[{"op": "replace", "pos": read_anchor, "lines": ["found"]}],
        )
        assert "E_STALE_ANCHOR" not in result


class TestBottomUpEquivalence:
    def test_batch_matches_sequential_descending_application(self, tmp_path):
        rng = random.Random(1234)
        for trial in range(20):
            lines = [f"L{i}" for i in range(1, 31)]
            targets = sorted(rng.sample(range(1, 31), 4))
            anchors = H.build_anchors(lines)
            edits = [
                {
                    "op": "replace",
                    "pos": f"{n}#{anchors[n - 1]}",
                    "lines": [f"X{n}a", f"X{n}b"],
                }
                for n in targets
            ]

            batched = tmp_path / f"batch{trial}.txt"
            batched.write_text("\n".join(lines), encoding="utf-8", newline="\n")
            EditTool(cwd=tmp_path, allowed_roots=[tmp_path]).run(
                path=batched.name, edits=edits
            )

            manual = list(lines)
            for n in reversed(targets):
                manual[n - 1:n] = [f"X{n}a", f"X{n}b"]

            assert batched.read_text(encoding="utf-8").splitlines() == manual
