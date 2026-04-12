import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
import yaml

load_dotenv()  # populate os.environ from .env before AgentConfig reads OPENAI_API_KEY

from agent.loop import AgentConfig, AgentLoop
from agent.registry import registry
import agent.tools  # noqa: F401 — side-effect: registers all tools


def main():
    parser = argparse.ArgumentParser(description="Driverless AGI coding agent")
    parser.add_argument("task", nargs="?", help="Task to run (reads from stdin if omitted)")
    parser.add_argument("--model", help="Model to use")
    parser.add_argument("--base-url", dest="base_url", help="API base URL")
    parser.add_argument("--max-iter", dest="max_iter", type=int, help="Max iterations")
    args = parser.parse_args()

    yaml_cfg: dict = {}
    if Path("config.yaml").exists():
        yaml_cfg = yaml.safe_load(Path("config.yaml").read_text()) or {}

    config = AgentConfig(
        model=args.model or yaml_cfg.get("model", "gpt-4o"),
        base_url=args.base_url or yaml_cfg.get("base_url", "https://api.openai.com/v1"),
        max_iterations=args.max_iter or yaml_cfg.get("max_iterations", 20),
    )

    task = args.task or sys.stdin.read().strip()
    if not task:
        parser.error("No task provided — pass as argument or pipe via stdin")

    result = AgentLoop(config, registry).run(task)
    print(result)


if __name__ == "__main__":
    main()
