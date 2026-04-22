import argparse
import json

from optimizer import optimize_prompt


def _exact_match(y_pred: str, y_true: str) -> float:
    return float(y_pred.strip().lower() == y_true.strip().lower())


def main():
    parser = argparse.ArgumentParser(
        description="Optimize a prompt using LLM feedback.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "seed_prompt",
        help="Initial prompt text. Prefix with @ to read from a file (e.g. @prompt.txt).",
    )
    parser.add_argument(
        "samples_file",
        help='Path to JSON file: [{"input": "...", "ground_truth": "..."}, ...]',
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Wall-clock timeout in seconds. Loop stops at max-iterations OR timeout, whichever is first.",
    )
    parser.add_argument("--history-output", default="history.json", help="Path to write history JSON")
    parser.add_argument("--temperature-generation", type=float, default=0.7)
    parser.add_argument("--temperature-analysis", type=float, default=0.3)
    args = parser.parse_args()

    # Support @file.txt syntax for long seed prompts
    if args.seed_prompt.startswith("@"):
        with open(args.seed_prompt[1:], encoding="utf-8") as f:
            seed_prompt = f.read().strip()
    else:
        seed_prompt = args.seed_prompt

    with open(args.samples_file, encoding="utf-8") as f:
        samples = json.load(f)

    print(f"Starting optimization: {len(samples)} sample(s), max {args.max_iterations} iteration(s)")
    if args.timeout:
        print(f"Timeout: {args.timeout}s")
    print(f"Seed prompt: {seed_prompt[:80]}{'...' if len(seed_prompt) > 80 else ''}\n")

    result = optimize_prompt(
        seed_prompt=seed_prompt,
        samples=samples,
        eval_fn=_exact_match,
        config_path=args.config,
        max_iterations=args.max_iterations,
        timeout_seconds=args.timeout,
        history_output_path=args.history_output,
        temperature_generation=args.temperature_generation,
        temperature_analysis=args.temperature_analysis,
    )

    print(f"\nDone. Stop reason: {result['stop_reason']}")
    print(f"Iterations run: {result['total_iterations']}")
    print(f"Best score: {result['best_score']:.4f} (iteration {result['best_iteration']})")
    print(f"\nBest prompt:\n{result['best_prompt']}")
    print(f"\nHistory written to: {args.history_output}")


if __name__ == "__main__":
    main()
