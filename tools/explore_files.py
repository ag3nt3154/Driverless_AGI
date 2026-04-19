from pathlib import Path

from agent.base_tool import BaseTool

_SYSTEM_PROMPT = """\
You are a focused file exploration agent. Answer the question using read, grep, and find only.

Guidelines:
- Use find to locate files by glob pattern.
- Use grep to search for identifiers, patterns, or keywords.
- Use read to inspect file contents as needed.
- Synthesise findings into a structured Markdown summary.
- Include file paths for every finding.
- Do NOT modify any files.\
"""


class ExploreFilesTool(BaseTool):
    name = "explore_files"
    description = (
        "Delegate broad file exploration to a sub-agent with read, grep, and find. "
        "Returns a structured Markdown summary. "
        "Use for open-ended discovery: mapping a module, finding all usages of a symbol, "
        "or understanding an unfamiliar subsystem. "
        "For targeted reads of specific known files, use read/grep/find directly."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Open-ended exploration question.",
            },
            "paths": {
                "type": "string",
                "description": (
                    "Optional comma-separated directory paths to focus on "
                    "(e.g. 'src/,tests/'). Omit for whole-project search."
                ),
            },
        },
        "required": ["task"],
    }

    def __init__(self, config, callbacks=None, cwd: Path = Path("."), allowed_roots=None):
        self._config = config
        self._callbacks = callbacks
        self._cwd = cwd
        self._allowed_roots = allowed_roots

    def run(self, task: str, paths: str | None = None) -> str:
        try:
            from agent.sub_agent import SubAgentConfig, SubAgentRunner
            from tools.find import FindTool
            from tools.grep import GrepTool
            from tools.read import ReadTool

            effective_roots = self._allowed_roots or [self._cwd]
            sub_tools = [
                ReadTool(cwd=self._cwd, allowed_roots=effective_roots),
                GrepTool(cwd=self._cwd, allowed_roots=effective_roots),
                FindTool(cwd=self._cwd, allowed_roots=effective_roots),
            ]
            full_task = task if not paths else f"{task}\n\nFocus on these paths: {paths}"
            runner = SubAgentRunner(
                config=self._config,
                tools=sub_tools,
                system_prompt=_SYSTEM_PROMPT,
                callbacks=self._callbacks,
                sub_cfg=SubAgentConfig(max_iterations=8, prefix="[explore-files]"),
            )
            return runner.run(full_task)
        except Exception as e:
            return f"[explore_files error] {e}"
