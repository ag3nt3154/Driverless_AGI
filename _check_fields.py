from agent.config_loader import resolve_model_config
from agent.tools import create_tool_registry

config = resolve_model_config()
reg = create_tool_registry(config=config)
tools = [name for name, _ in reg.list_tools()]
print("Registered tools:", tools)
print("switch_model present:", "switch_model" in tools)
print("plan_config set:", config.plan_config is not None)
print("worker_config set:", config.worker_config is not None)
