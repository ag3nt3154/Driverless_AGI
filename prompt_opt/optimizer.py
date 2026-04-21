"""Hill-climb prompt optimization loop with direct-call and agent modes."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from prompt_opt.evaluator import evaluate_prompt, load_samples
from prompt_opt.llm_client import LLMClient, LLMClientConfig, LLMParseError
from prompt_opt.scoring import (
    DatasetStats,
    SampleResult,
    compute_dataset_accuracy,
    format_failure_table,
    format_sample_details,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_DIRECT_SYSTEM = """\
You are an expert prompt engineer specializing in prompts that produce structured JSON output.

Your task: improve the given prompt by making exactly ONE targeted change that will increase
field-level JSON accuracy on the evaluation dataset.

The prompt MUST retain the {input_json} placeholder — do not remove or rename it.
Do NOT modify the "RESPONSE FORMAT" section at the bottom of the prompt (if present).

Focus on the single highest-impact improvement. Do not rewrite the entire prompt.
Common issues to look for:
- Missing instructions for specific field types (numbers vs strings, booleans, percentages)
- Ambiguous or missing field names that the model doesn't know to extract
- Missing examples for fields that fail most often
- Incorrect assumed output schema

Respond with ONLY this JSON structure — no preamble, no explanation, no markdown:
{"new_prompt": "<complete revised prompt>", "change_description": "<one sentence, max 120 chars>"}
"""

_DIRECT_USER_TEMPLATE = """\
## Current Best Prompt

{current_prompt}

## Accuracy: {score:.1%} ({correct}/{total} fields correct across {n_samples} samples, {parse_failures} parse failures)

## Field Failure Summary

{failure_table}

## Sample-Level Details

{sample_details}
{rejected_section}
Suggest ONE improvement addressing the most frequent failures."""

_AGENT_SYSTEM = """\
You are an expert prompt engineer with file access.

Your task: make exactly ONE targeted improvement to the prompt stored at the path you will be given,
in order to increase field-level JSON accuracy.

Rules:
- The prompt MUST retain the {{input_json}} placeholder.
- Do NOT modify the "RESPONSE FORMAT" section at the bottom of the prompt.
- Write the COMPLETE revised prompt to: {candidate_path}
- Write a ONE-SENTENCE change description (max 120 chars) to: {desc_path}
- Do not output any other files.
"""

_AGENT_TASK_TEMPLATE = """\
Improve the prompt at: {prompt_path}

## Accuracy: {score:.1%} ({correct}/{total} fields correct across {n_samples} samples)

## Field Failure Summary

{failure_table}

## Sample-Level Details

{sample_details}
{rejected_section}
Make ONE improvement targeting the most frequent failures.
Write the revised prompt to: {candidate_path}
Write the change description to: {desc_path}"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IterationRecord:
    iteration: int
    timestamp: str          # ISO 8601 UTC
    prompt: str
    score: float
    correct_fields: int
    total_fields: int
    n_samples: int
    parse_failures: int
    change_description: str  # "" for iteration 0
    accepted: bool
    failure_summary: list[dict] = field(default_factory=list)


@dataclass
class OptimizationConfig:
    n_iterations: int
    timeout_seconds: int | None
    data_dir: Path
    output_dir: Path
    initial_prompt: str
    eval_client: LLMClient
    optimizer_llm_cfg: LLMClientConfig   # used in direct mode
    optimizer_mode: str                  # "direct" | "agent"
    optimizer_agent_cfg: dict            # raw dict for building AgentConfig in agent mode
    max_retries: int = 3
    verbose: bool = False


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

class Optimizer:
    def __init__(self, cfg: OptimizationConfig) -> None:
        self._cfg = cfg
        self._history: list[IterationRecord] = []
        self._best_prompt: str = cfg.initial_prompt
        self._best_score: float = -1.0
        self._best_stats: DatasetStats | None = None
        self._samples: list[dict] = load_samples(cfg.data_dir)
        cfg.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> IterationRecord:
        print(f"\n=== Prompt Optimization ({self._cfg.optimizer_mode} mode) ===")
        print(f"Samples: {len(self._samples)}  |  Max iterations: {self._cfg.n_iterations}")
        print()

        # Iteration 0: evaluate initial prompt
        record = self._evaluate_and_record(
            prompt=self._best_prompt,
            iteration=0,
            change_description="",
            accepted=True,
        )
        self._best_score = record.score
        self._best_stats = self._stats_from_record(record)
        self._save_outputs()

        if self._cfg.n_iterations == 0:
            self._plot()
            return record

        start_time = time.time()
        rejected_history: list[str] = []

        for i in range(1, self._cfg.n_iterations + 1):
            # Timeout check
            if self._cfg.timeout_seconds is not None:
                elapsed = time.time() - start_time
                if elapsed >= self._cfg.timeout_seconds:
                    print(f"\nTimeout reached after {elapsed:.0f}s — stopping.")
                    break

            print(f"\n--- Iteration {i}/{self._cfg.n_iterations} ---")

            # Ask optimizer for one improvement
            new_prompt, change_desc = self._call_optimizer(
                self._best_prompt, self._best_stats, rejected_history
            )

            # Validate {input_json} placeholder is present
            if "{input_json}" not in new_prompt:
                print("  [warn] Optimizer dropped {input_json} placeholder — reverting.")
                new_prompt = self._best_prompt
                change_desc = "optimizer_invalid_placeholder"

            # Evaluate candidate
            results = evaluate_prompt(
                new_prompt, self._cfg.eval_client, self._samples, self._cfg.verbose
            )
            stats = compute_dataset_accuracy(results)
            accepted = stats.accuracy > self._best_score

            record = IterationRecord(
                iteration=i,
                timestamp=_now_iso(),
                prompt=new_prompt,
                score=stats.accuracy,
                correct_fields=stats.correct_fields,
                total_fields=stats.total_fields,
                n_samples=stats.n_samples,
                parse_failures=stats.parse_failures,
                change_description=change_desc,
                accepted=accepted,
                failure_summary=stats.failure_summary[:10],
            )
            self._history.append(record)

            if accepted:
                self._best_prompt = new_prompt
                self._best_score = stats.accuracy
                self._best_stats = stats
                rejected_history = []  # reset on acceptance
                print(f"  ACCEPTED  score={stats.accuracy:.1%}  change={change_desc!r}")
            else:
                rejected_history.append(change_desc)
                print(f"  REJECTED  score={stats.accuracy:.1%} (best={self._best_score:.1%})  change={change_desc!r}")

            self._save_outputs()

            if self._best_score >= 1.0:
                print("\nPerfect score reached — stopping.")
                break

        self._plot()
        best_record = next(r for r in reversed(self._history) if r.accepted)
        return best_record

    # ------------------------------------------------------------------
    # Optimizer dispatch
    # ------------------------------------------------------------------

    def _call_optimizer(
        self,
        current_prompt: str,
        stats: DatasetStats,
        rejected_history: list[str],
    ) -> tuple[str, str]:
        if self._cfg.optimizer_mode == "agent":
            return self._call_agent(current_prompt, stats, rejected_history)
        return self._call_direct(current_prompt, stats, rejected_history)

    def _call_direct(
        self,
        current_prompt: str,
        stats: DatasetStats,
        rejected_history: list[str],
    ) -> tuple[str, str]:
        rejected_section = ""
        if rejected_history:
            bullets = "\n".join(f"- {c}" for c in rejected_history)
            rejected_section = f"\n## Previously Tried Changes (FAILED — do not repeat)\n{bullets}\n"

        user_msg = _DIRECT_USER_TEMPLATE.format(
            current_prompt=current_prompt,
            score=stats.accuracy,
            correct=stats.correct_fields,
            total=stats.total_fields,
            n_samples=stats.n_samples,
            parse_failures=stats.parse_failures,
            failure_table=format_failure_table(stats),
            sample_details=format_sample_details(stats),
            rejected_section=rejected_section,
        )

        client = LLMClient(self._cfg.optimizer_llm_cfg)
        try:
            result = client.call_json([
                {"role": "system", "content": _DIRECT_SYSTEM},
                {"role": "user", "content": user_msg},
            ])
            new_prompt = result.get("new_prompt", "")
            change_desc = result.get("change_description", "no description")
            if not new_prompt:
                raise ValueError("optimizer returned empty new_prompt")
            return new_prompt, str(change_desc)[:120]
        except (LLMParseError, ValueError, KeyError) as exc:
            print(f"  [warn] Optimizer call failed: {exc} — skipping iteration.")
            return current_prompt, "optimizer_failed"

    def _call_agent(
        self,
        current_prompt: str,
        stats: DatasetStats,
        rejected_history: list[str],
    ) -> tuple[str, str]:
        candidate_path = self._cfg.output_dir / "candidate_prompt.txt"
        desc_path = self._cfg.output_dir / "change_description.txt"

        # Write the current best prompt so the agent can read it
        prompt_path = self._cfg.output_dir / "current_prompt_for_agent.txt"
        prompt_path.write_text(current_prompt, encoding="utf-8")

        rejected_section = ""
        if rejected_history:
            bullets = "\n".join(f"- {c}" for c in rejected_history)
            rejected_section = f"\n## Previously Tried Changes (FAILED — do not repeat)\n{bullets}\n"

        task = _AGENT_TASK_TEMPLATE.format(
            prompt_path=str(prompt_path),
            score=stats.accuracy,
            correct=stats.correct_fields,
            total=stats.total_fields,
            n_samples=stats.n_samples,
            failure_table=format_failure_table(stats),
            sample_details=format_sample_details(stats),
            rejected_section=rejected_section,
            candidate_path=str(candidate_path),
            desc_path=str(desc_path),
        )

        system = _AGENT_SYSTEM.format(
            candidate_path=str(candidate_path),
            desc_path=str(desc_path),
        )

        try:
            runner = _build_sub_agent_runner(self._cfg.optimizer_agent_cfg, system)
            runner.run(task)

            if not candidate_path.exists():
                raise FileNotFoundError(f"Agent did not write {candidate_path}")
            new_prompt = candidate_path.read_text(encoding="utf-8").strip()
            change_desc = (
                desc_path.read_text(encoding="utf-8").strip()
                if desc_path.exists()
                else "no description"
            )
            return new_prompt, change_desc[:120]
        except Exception as exc:
            print(f"  [warn] Agent optimizer failed: {exc} — skipping iteration.")
            return current_prompt, "optimizer_failed"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _evaluate_and_record(
        self,
        prompt: str,
        iteration: int,
        change_description: str,
        accepted: bool,
    ) -> IterationRecord:
        print(f"Evaluating {'initial prompt' if iteration == 0 else f'iteration {iteration}'}...")
        results = evaluate_prompt(
            prompt, self._cfg.eval_client, self._samples, self._cfg.verbose
        )
        stats = compute_dataset_accuracy(results)

        record = IterationRecord(
            iteration=iteration,
            timestamp=_now_iso(),
            prompt=prompt,
            score=stats.accuracy,
            correct_fields=stats.correct_fields,
            total_fields=stats.total_fields,
            n_samples=stats.n_samples,
            parse_failures=stats.parse_failures,
            change_description=change_description,
            accepted=accepted,
            failure_summary=stats.failure_summary[:10],
        )
        self._history.append(record)
        print(f"  Score: {stats.accuracy:.1%} ({stats.correct_fields}/{stats.total_fields} fields)")
        return record

    def _stats_from_record(self, record: IterationRecord) -> DatasetStats:
        """Re-run eval to get a full DatasetStats object for the best prompt."""
        results = evaluate_prompt(
            record.prompt, self._cfg.eval_client, self._samples, verbose=False
        )
        return compute_dataset_accuracy(results)

    def _save_outputs(self) -> None:
        """Persist history.json and best_prompt.txt after every iteration."""
        output_dir = self._cfg.output_dir

        history_data = {
            "best_score": self._best_score,
            "best_iteration": next(
                (r.iteration for r in reversed(self._history) if r.accepted), 0
            ),
            "eval_model": self._cfg.eval_client._cfg.model,
            "optimizer_mode": self._cfg.optimizer_mode,
            "n_samples": len(self._samples),
            "iterations": [asdict(r) for r in self._history],
        }
        (output_dir / "history.json").write_text(
            json.dumps(history_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (output_dir / "best_prompt.txt").write_text(self._best_prompt, encoding="utf-8")

    def _plot(self) -> None:
        try:
            from prompt_opt.viz import plot_history
            plot_history(
                [asdict(r) for r in self._history],
                self._cfg.output_dir / "score_plot.png",
            )
            print(f"\nGraph saved to {self._cfg.output_dir / 'score_plot.png'}")
        except Exception as exc:
            print(f"  [warn] Could not generate graph: {exc}")


# ---------------------------------------------------------------------------
# Agent runner builder (lazy import to avoid hard dep when using direct mode)
# ---------------------------------------------------------------------------

def _build_sub_agent_runner(agent_cfg_dict: dict, system_prompt: str):
    """Build a SubAgentRunner from raw config dict for agent-mode optimization."""
    from agent.loop import AgentConfig
    from agent.sub_agent import SubAgentRunner, SubAgentConfig
    from tools.read import ReadTool
    from tools.write import WriteTool
    from tools.edit import EditTool

    cfg = AgentConfig(
        model=agent_cfg_dict["model"],
        base_url=agent_cfg_dict["api_url"],
        api_key=agent_cfg_dict["api_key"],
        thinking="none",
    )

    cwd = Path(".").resolve()
    tools = [
        ReadTool(cwd=cwd, allowed_roots=[cwd]),
        WriteTool(cwd=cwd, allowed_roots=[cwd]),
        EditTool(cwd=cwd, allowed_roots=[cwd]),
    ]

    return SubAgentRunner(
        config=cfg,
        tools=tools,
        system_prompt=system_prompt,
        sub_cfg=SubAgentConfig(prefix="[prompt-optimizer]"),
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
