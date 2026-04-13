import argparse
import sys

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env before config_loader reads API keys

from agent.config_loader import resolve_model_config
from agent.loop import AgentLoop
from agent.registry import registry
import agent.tools  # noqa: F401 — side-effect: registers all tools


def main():
    parser = argparse.ArgumentParser(description="Driverless AGI coding agent")
    parser.add_argument("task", nargs="?", help="Task to run (reads from stdin if omitted)")
    parser.add_argument("--model", help="Model ID from config.yaml (e.g. gpt-4o-openai)")
    parser.add_argument("--base-url", dest="base_url", help="[deprecated] URL is now set per-model in config.yaml")
    parser.add_argument("--max-iter", dest="max_iter", type=int, help="Max iterations")
    args = parser.parse_args()

    if args.base_url:
        print("Warning: --base-url is deprecated. Configure the URL in config.yaml under models.", file=sys.stderr)

    config = resolve_model_config(model_id=args.model)
    if args.max_iter:
        config.max_iterations = args.max_iter

    task = args.task or sys.stdin.read().strip()
    if not task:
        parser.error("No task provided — pass as argument or pipe via stdin")

    result = AgentLoop(config, registry).run(task)
    print(result)


if __name__ == "__main__":
    main()
