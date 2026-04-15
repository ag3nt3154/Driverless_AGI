"""Quick diagnostic: inspect the response object from OpenRouter with thinking."""
import openai, os
from dotenv import load_dotenv
load_dotenv()

client = openai.OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)
resp = client.chat.completions.create(
    model="qwen/qwen3.5-27b",
    messages=[{"role": "user", "content": "what is 2+2"}],
    extra_body={"reasoning": {"effort": "high"}},
)
msg = resp.choices[0].message
print("=== message type:", type(msg))
print("=== attrs:", [a for a in dir(msg) if not a.startswith("_")])
print("=== reasoning_content:", repr(getattr(msg, "reasoning_content", "NOT_FOUND")))
print("=== model_extra:", msg.model_extra)
print("=== content:", repr(msg.content))
print()
print("=== usage:", resp.usage)
print("=== usage attrs:", [a for a in dir(resp.usage) if not a.startswith("_")])
print("=== completion_tokens_details:", repr(getattr(resp.usage, "completion_tokens_details", "NOT_FOUND")))
if hasattr(resp.usage, "model_extra"):
    print("=== usage.model_extra:", resp.usage.model_extra)
