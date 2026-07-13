import json

import pytest

from benchmarks.dagi_eval import scoring


# ── outputs_match ────────────────────────────────────────────────────────
def test_outputs_match_exact_and_nested():
    a = {"x": [1, "s", {"y": 2}], "z": None}
    assert scoring.outputs_match(a, json.loads(json.dumps(a)))


def test_outputs_match_float_tolerance():
    assert scoring.outputs_match({"v": 1.0000000001}, {"v": 1.0})
    assert not scoring.outputs_match({"v": 1.01}, {"v": 1.0})


def test_outputs_match_type_and_shape_mismatches():
    assert not scoring.outputs_match([1, 2], [1, 2, 3])
    assert not scoring.outputs_match({"a": 1}, {"b": 1})
    assert not scoring.outputs_match("1", 1)
    assert not scoring.outputs_match(1.0, "1.0")


def test_outputs_match_int_float_close():
    assert scoring.outputs_match(2, 2.0)


# ── roc_auc ──────────────────────────────────────────────────────────────
def test_roc_auc_perfect_and_reversed():
    y = [0, 0, 1, 1]
    assert scoring.roc_auc(y, [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)
    assert scoring.roc_auc(y, [0.9, 0.8, 0.2, 0.1]) == pytest.approx(0.0)


def test_roc_auc_ties_average():
    assert scoring.roc_auc([0, 1], [0.5, 0.5]) == pytest.approx(0.5)


def test_roc_auc_known_value():
    # pairs: (0.4>0.3)=1, (0.4>0.5)=0, (0.6>0.3)=1, (0.6>0.5)=1 -> 3/4
    assert scoring.roc_auc([0, 0, 1, 1], [0.3, 0.5, 0.4, 0.6]) == pytest.approx(0.75)


def test_roc_auc_degenerate_raises():
    with pytest.raises(ValueError):
        scoring.roc_auc([1, 1], [0.1, 0.2])


# ── score_ds_task validation ────────────────────────────────────────────
def _make_ds_task(tmp_path, labels_rows, meta=None):
    task = tmp_path / "ds_task"
    (task / "hidden").mkdir(parents=True)
    (task / "hidden" / "test_labels.csv").write_text(
        "id,label\n" + "\n".join(labels_rows) + "\n", encoding="utf-8")
    (task / "hidden" / "meta.json").write_text(
        json.dumps(meta or {"baseline_auc": 0.7, "oracle_auc": 0.9}), encoding="utf-8")
    return task


def test_score_ds_missing_predictions(tmp_path):
    task = _make_ds_task(tmp_path, ["1,0", "2,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    res = scoring.score_ds_task(task, ws)
    assert res["ds_score"] == 0.0
    assert "not found" in res["error"]


def test_score_ds_wrong_ids(tmp_path):
    task = _make_ds_task(tmp_path, ["1,0", "2,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "predictions.csv").write_text(
        "id,probability\n1,0.2\n99,0.8\n", encoding="utf-8")
    res = scoring.score_ds_task(task, ws)
    assert res["ds_score"] == 0.0
    assert res["error"] is not None


def test_score_ds_non_numeric(tmp_path):
    task = _make_ds_task(tmp_path, ["1,0", "2,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "predictions.csv").write_text(
        "id,probability\n1,abc\n2,0.8\n", encoding="utf-8")
    res = scoring.score_ds_task(task, ws)
    assert res["ds_score"] == 0.0
    assert res["error"] is not None


def test_score_ds_happy_path(tmp_path):
    # perfect ranking -> auc 1.0 -> ds_score (1.0-0.5)/(0.7-0.5) = 2.5
    task = _make_ds_task(tmp_path, ["1,0", "2,1", "3,0", "4,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "predictions.csv").write_text(
        "id,probability\n1,0.1\n2,0.9\n3,0.2\n4,0.8\n", encoding="utf-8")
    res = scoring.score_ds_task(task, ws)
    assert res["error"] is None
    assert res["auc"] == pytest.approx(1.0)
    assert res["ds_score"] == pytest.approx(2.5)
