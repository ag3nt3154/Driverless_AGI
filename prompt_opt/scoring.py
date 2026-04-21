"""Pure, side-effect-free field-by-field JSON comparison for prompt evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldError:
    path: str          # dot-notation path, e.g. "nested.score"
    expected: Any
    actual: Any        # None means the field was absent in the LLM output
    error_type: str    # "wrong_value" | "missing_field" | "wrong_type"


@dataclass
class SampleResult:
    sample_id: str
    correct: int
    total: int
    errors: list[FieldError]
    raw_output: str
    parse_failed: bool = False

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total > 0 else 0.0


@dataclass
class DatasetStats:
    accuracy: float
    correct_fields: int
    total_fields: int
    n_samples: int
    parse_failures: int
    # [{path, failure_count, example_expected, example_actual}] sorted by failure_count desc
    failure_summary: list[dict]
    sample_results: list[SampleResult]


def _coerce(actual: Any, expected: Any) -> Any:
    """Attempt type coercion of actual to match expected's type, unambiguously only."""
    if type(actual) is type(expected):
        return actual
    # string → bool
    if isinstance(expected, bool) and isinstance(actual, str):
        if actual.lower() == "true":
            return True
        if actual.lower() == "false":
            return False
    # string → int / float
    if isinstance(expected, (int, float)) and isinstance(actual, str):
        try:
            if isinstance(expected, int) and "." not in actual:
                return int(actual)
            return float(actual)
        except ValueError:
            pass
    # int → float or vice versa (1 == 1.0)
    if isinstance(expected, float) and isinstance(actual, int):
        return float(actual)
    if isinstance(expected, int) and isinstance(actual, float) and actual == int(actual):
        return int(actual)
    return actual


def compare_json(
    actual: Any,
    expected: Any,
    path: str = "",
) -> tuple[int, int, list[FieldError]]:
    """
    Recursively compare actual against expected.
    Only keys present in expected are evaluated (extra keys in actual are ignored).
    Returns (correct_count, total_count, errors).
    """
    errors: list[FieldError] = []
    correct = 0
    total = 0

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            actual = {}
        for key, exp_val in expected.items():
            child_path = f"{path}.{key}" if path else key
            act_val = actual.get(key)
            if act_val is None and key not in actual:
                # Field entirely missing
                c, t, e = _count_leaves(exp_val, child_path, missing=True)
                errors.extend(e)
                total += t
            else:
                c, t, e = compare_json(act_val, exp_val, child_path)
                correct += c
                total += t
                errors.extend(e)
        return correct, total, errors

    if isinstance(expected, list):
        if not isinstance(actual, list):
            actual = []
        for i, exp_item in enumerate(expected):
            child_path = f"{path}[{i}]"
            if i < len(actual):
                c, t, e = compare_json(actual[i], exp_item, child_path)
                correct += c
                total += t
                errors.extend(e)
            else:
                c, t, e = _count_leaves(exp_item, child_path, missing=True)
                errors.extend(e)
                total += t
        return correct, total, errors

    # Leaf value comparison
    total = 1
    coerced = _coerce(actual, expected)
    if coerced == expected:
        correct = 1
    else:
        err_type = "missing_field" if actual is None else (
            "wrong_type" if type(coerced) is not type(expected) else "wrong_value"
        )
        errors.append(FieldError(path=path, expected=expected, actual=actual, error_type=err_type))
    return correct, total, errors


def _count_leaves(value: Any, path: str, missing: bool) -> tuple[int, int, list[FieldError]]:
    """Count all leaf fields under value as errors (field absent in actual output)."""
    if isinstance(value, dict):
        errors: list[FieldError] = []
        total = 0
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            _, t, e = _count_leaves(child, child_path, missing)
            errors.extend(e)
            total += t
        return 0, total, errors
    if isinstance(value, list):
        errors = []
        total = 0
        for i, item in enumerate(value):
            _, t, e = _count_leaves(item, f"{path}[{i}]", missing)
            errors.extend(e)
            total += t
        return 0, total, errors
    # Leaf
    err = FieldError(path=path, expected=value, actual=None, error_type="missing_field")
    return 0, 1, [err]


def score_sample(
    sample_id: str,
    actual_json: dict,
    ground_truth: dict,
    raw_output: str,
) -> SampleResult:
    correct, total, errors = compare_json(actual_json, ground_truth)
    return SampleResult(
        sample_id=sample_id,
        correct=correct,
        total=total,
        errors=errors,
        raw_output=raw_output,
    )


def compute_dataset_accuracy(results: list[SampleResult]) -> DatasetStats:
    total_correct = sum(r.correct for r in results)
    total_fields = sum(r.total for r in results)
    parse_failures = sum(1 for r in results if r.parse_failed)
    accuracy = total_correct / total_fields if total_fields > 0 else 0.0

    # Build failure summary: count how often each field path fails
    failure_counts: dict[str, dict] = {}
    for result in results:
        for err in result.errors:
            if err.path not in failure_counts:
                failure_counts[err.path] = {
                    "path": err.path,
                    "failure_count": 0,
                    "example_expected": err.expected,
                    "example_actual": err.actual,
                }
            failure_counts[err.path]["failure_count"] += 1

    failure_summary = sorted(
        failure_counts.values(),
        key=lambda x: x["failure_count"],
        reverse=True,
    )

    return DatasetStats(
        accuracy=accuracy,
        correct_fields=total_correct,
        total_fields=total_fields,
        n_samples=len(results),
        parse_failures=parse_failures,
        failure_summary=failure_summary,
        sample_results=results,
    )


def format_failure_table(stats: DatasetStats) -> str:
    """Return a markdown table of field failures for use in the optimizer prompt."""
    if not stats.failure_summary:
        return "_No field failures — all fields correct._"

    lines = [
        "| Field Path | Failures | Example Expected | Example Actual |",
        "|------------|----------|-----------------|----------------|",
    ]
    for entry in stats.failure_summary[:20]:  # cap at 20 rows
        path = entry["path"]
        count = f"{entry['failure_count']}/{stats.n_samples}"
        exp = str(entry["example_expected"])[:40]
        act = str(entry["example_actual"])[:40]
        lines.append(f"| `{path}` | {count} | `{exp}` | `{act}` |")
    return "\n".join(lines)


def format_sample_details(stats: DatasetStats, max_errors_per_sample: int = 3) -> str:
    """Return per-sample error details for use in the optimizer prompt."""
    parts = []
    for result in stats.sample_results:
        score_str = f"{result.correct}/{result.total}"
        if result.parse_failed:
            parts.append(f"**{result.sample_id}**: PARSE FAILED (score 0/{result.total})")
            continue
        if not result.errors:
            parts.append(f"**{result.sample_id}**: {score_str} ✓ (perfect)")
            continue
        error_lines = []
        for err in result.errors[:max_errors_per_sample]:
            error_lines.append(
                f"  - `{err.path}`: expected `{err.expected}`, got `{err.actual}` ({err.error_type})"
            )
        if len(result.errors) > max_errors_per_sample:
            error_lines.append(f"  - _...and {len(result.errors) - max_errors_per_sample} more_")
        parts.append(f"**{result.sample_id}**: {score_str}\n" + "\n".join(error_lines))
    return "\n\n".join(parts)
