import json
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from api_client import APIClient, APIError
from config import load_config

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / ".dagi" / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


_ANALYSIS_SYSTEM = _load_prompt("prompt_opt_analysis_system.md")
_ANALYSIS_USER = _load_prompt("prompt_opt_analysis_user.md")
_IMPROVEMENT_SYSTEM = _load_prompt("prompt_opt_improvement_system.md")
_IMPROVEMENT_USER = _load_prompt("prompt_opt_improvement_user.md")


def optimize_prompt(
    seed_prompt: str,
    samples: list[dict],
    eval_fn: Callable,
    config_path: str = "config.yaml",
    max_iterations: int = 10,
    timeout_seconds: float | None = None,
    history_output_path: str | None = None,
    temperature_generation: float = 0.7,
    temperature_analysis: float = 0.3,
) -> dict:
    """
    Run the prompt optimization loop.

    Args:
        seed_prompt: Starting prompt text.
        samples: List of {"input": str, "ground_truth": str} dicts.
        eval_fn: Callable(y_pred, y_true) -> float. Mirrors sklearn.metrics signature.
        config_path: Path to config.yaml.
        max_iterations: Maximum number of improvement iterations (not counting seed).
        timeout_seconds: Wall-clock timeout in seconds. None means no limit.
        history_output_path: If set, write history JSON here after each iteration.
        temperature_generation: Temperature for generation endpoint.
        temperature_analysis: Temperature for analysis/improvement calls.

    Returns:
        {
            "best_prompt": str,
            "best_score": float,
            "best_iteration": int,
            "history": list[dict],
            "total_iterations": int,
            "stop_reason": "max_iterations" | "timeout",
        }
    """
    cfg = load_config(config_path)
    gen_client = APIClient(
        cfg.generation_endpoint.api_url,
        cfg.generation_endpoint.api_key,
        cfg.generation_endpoint.model_name,
    )
    analysis_client = APIClient(
        cfg.analysis_endpoint.api_url,
        cfg.analysis_endpoint.api_key,
        cfg.analysis_endpoint.model_name,
    )

    history: list[dict] = []
    start_time = time.time()

    # --- Seed evaluation ---
    seed_result = _evaluate_prompt(gen_client, eval_fn, seed_prompt, samples, temperature_generation)
    seed_entry = _make_history_entry(0, seed_prompt, seed_result, "seed")
    history.append(seed_entry)
    _maybe_save(history, history_output_path)

    best_prompt = seed_prompt
    best_score = seed_result["mean_score"]
    best_iteration = 0
    best_sample_results = seed_result["per_sample"]

    stop_reason = "max_iterations"

    for iteration in range(1, max_iterations + 1):
        if timeout_seconds is not None and (time.time() - start_time) >= timeout_seconds:
            stop_reason = "timeout"
            break

        try:
            analysis = _analyze_errors(
                analysis_client, best_prompt, best_sample_results, history, temperature_analysis
            )
            new_prompt, modification = _improve_prompt(
                analysis_client,
                best_prompt,
                analysis,
                best_sample_results,
                history,
                best_score,
                best_iteration,
                temperature_analysis,
            )
            new_result = _evaluate_prompt(gen_client, eval_fn, new_prompt, samples, temperature_generation)
        except APIError as e:
            entry = _make_history_entry(iteration, best_prompt, None, f"FAILED: {e}")
            history.append(entry)
            _maybe_save(history, history_output_path)
            continue

        entry = _make_history_entry(iteration, new_prompt, new_result, modification)
        history.append(entry)

        if new_result["mean_score"] > best_score:
            best_prompt = new_prompt
            best_score = new_result["mean_score"]
            best_iteration = iteration
            best_sample_results = new_result["per_sample"]

        _maybe_save(history, history_output_path)

    return {
        "best_prompt": best_prompt,
        "best_score": best_score,
        "best_iteration": best_iteration,
        "history": history,
        "total_iterations": len([h for h in history if h["iteration"] > 0]),
        "stop_reason": stop_reason,
    }


def _evaluate_prompt(
    gen_client: APIClient,
    eval_fn: Callable,
    prompt: str,
    samples: list[dict],
    temperature: float,
) -> dict:
    """Run prompt against all samples and score with eval_fn. Returns mean + per-sample detail."""
    per_sample = []
    for sample in samples:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": sample["input"]},
        ]
        output = gen_client.complete(messages, temperature=temperature)
        score = float(eval_fn(output, sample["ground_truth"]))
        per_sample.append({
            "input": sample["input"],
            "output": output,
            "ground_truth": sample["ground_truth"],
            "score": score,
        })

    mean_score = sum(s["score"] for s in per_sample) / len(per_sample)
    return {"mean_score": mean_score, "per_sample": per_sample}


def _analyze_errors(
    client: APIClient,
    prompt: str,
    sample_results: list[dict],
    history: list[dict],
    temperature: float,
) -> str:
    sample_text = _format_sample_results(sample_results)
    history_json = _format_history_for_llm(history)
    messages = [
        {"role": "system", "content": _ANALYSIS_SYSTEM},
        {"role": "user", "content": _ANALYSIS_USER.format(
            prompt=prompt,
            sample_results=sample_text,
            history_json=history_json,
        )},
    ]
    return client.complete(messages, temperature=temperature)


def _improve_prompt(
    client: APIClient,
    prompt: str,
    analysis: str,
    sample_results: list[dict],
    history: list[dict],
    best_score: float,
    best_iteration: int,
    temperature: float,
) -> tuple[str, str]:
    """Returns (new_prompt, modification_description)."""
    sample_text = _format_sample_results(sample_results)
    history_json = _format_history_for_llm(history)
    messages = [
        {"role": "system", "content": _IMPROVEMENT_SYSTEM},
        {"role": "user", "content": _IMPROVEMENT_USER.format(
            best_iteration=best_iteration,
            best_score=best_score,
            prompt=prompt,
            analysis=analysis,
            sample_results=sample_text,
            history_json=history_json,
        )},
    ]
    response = client.complete(messages, temperature=temperature)

    # Parse MODIFICATION: line out of response
    new_prompt = response
    modification = "No modification description provided."
    if "\nMODIFICATION:" in response:
        parts = response.rsplit("\nMODIFICATION:", 1)
        new_prompt = parts[0].strip()
        modification = parts[1].strip()

    return new_prompt, modification


def _make_history_entry(
    iteration: int,
    prompt: str,
    result: dict | None,
    modification: str,
) -> dict:
    return {
        "iteration": iteration,
        "prompt": prompt,
        "score": result["mean_score"] if result else None,
        "modification": modification,
        "datetime": datetime.now(timezone.utc).isoformat(),
        "per_sample_scores": result["per_sample"] if result else [],
    }


def _format_history_for_llm(history: list[dict]) -> str:
    """Compact JSON of history entries without per_sample_scores detail."""
    slim = [
        {
            "iteration": h["iteration"],
            "score": h["score"],
            "modification": h["modification"],
            "datetime": h["datetime"],
            "prompt_preview": h["prompt"][:120] + ("..." if len(h["prompt"]) > 120 else ""),
        }
        for h in history
    ]
    return json.dumps(slim, separators=(",", ":"))


def _format_sample_results(sample_results: list[dict]) -> str:
    lines = []
    for i, s in enumerate(sample_results, 1):
        score_str = f"{s['score']:.4f}" if s.get("score") is not None else "N/A"
        lines.append(
            f"Sample {i}:\n"
            f"  Input: {s['input']}\n"
            f"  Output: {s['output']}\n"
            f"  Ground Truth: {s['ground_truth']}\n"
            f"  Score: {score_str}"
        )
    return "\n\n".join(lines)


def _maybe_save(history: list[dict], path: str | None) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
