"""Run a prompt against all data samples and return per-sample scores."""
from __future__ import annotations

import json
from pathlib import Path

from prompt_opt.llm_client import LLMClient, LLMParseError
from prompt_opt.scoring import SampleResult, score_sample

# This suffix is appended to every eval system message and must never be modified
# by the optimizer (it is hidden from the optimizer prompt).
_RESPONSE_FORMAT_SUFFIX = (
    "\n\n---\nRESPONSE FORMAT (do not modify): "
    "Respond with ONLY a valid JSON object. No markdown fences. No explanation. No extra keys."
)


def load_samples(data_dir: Path) -> list[dict]:
    """Load all *.json files from data_dir. Each must have 'id', 'input', 'ground_truth'."""
    samples = []
    for path in sorted(data_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "id" not in data or "input" not in data or "ground_truth" not in data:
            raise ValueError(
                f"Sample file {path.name} must have 'id', 'input', and 'ground_truth' keys."
            )
        samples.append(data)
    if not samples:
        raise FileNotFoundError(f"No sample JSON files found in {data_dir}")
    return samples


def build_eval_messages(prompt: str, input_data: dict) -> list[dict]:
    """
    Build the message list for one eval call.
    Fills {input_json} in the prompt and appends the non-modifiable format suffix.
    The input is also passed as a user message for models that work better with
    instruction/content separation.
    """
    input_json_str = json.dumps(input_data, indent=2, ensure_ascii=False)
    # Fill placeholder; if missing we fall back to appending the input at the bottom
    if "{input_json}" in prompt:
        system_content = prompt.replace("{input_json}", input_json_str)
    else:
        system_content = prompt + f"\n\nInput:\n{input_json_str}"
    system_content += _RESPONSE_FORMAT_SUFFIX

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "Process the above input and return your JSON response."},
    ]


def evaluate_prompt(
    prompt: str,
    client: LLMClient,
    samples: list[dict],
    verbose: bool = False,
) -> list[SampleResult]:
    """
    Run the prompt against all samples.
    On LLMParseError: records parse_failed=True, score=0/total, continues.
    """
    results: list[SampleResult] = []

    for sample in samples:
        sample_id = sample["id"]
        input_data = sample["input"]
        ground_truth = sample["ground_truth"]

        messages = build_eval_messages(prompt, input_data)

        try:
            output_json = client.call_json(messages)
            result = score_sample(sample_id, output_json, ground_truth, raw_output="")
        except LLMParseError as exc:
            # Count all expected fields as missed
            from prompt_opt.scoring import _count_leaves
            _, total, errors = _count_leaves(ground_truth, "", missing=True)
            result = SampleResult(
                sample_id=sample_id,
                correct=0,
                total=total,
                errors=errors,
                raw_output=exc.raw_response,
                parse_failed=True,
            )

        results.append(result)

        if verbose:
            status = "PARSE FAIL" if result.parse_failed else f"{result.correct}/{result.total}"
            print(f"  [{sample_id}] {status}")
            for err in result.errors[:5]:
                print(f"    {err.path}: expected={err.expected!r} actual={err.actual!r}")
            if len(result.errors) > 5:
                print(f"    ...and {len(result.errors) - 5} more errors")

    return results
