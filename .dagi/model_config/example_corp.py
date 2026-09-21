"""Example client profile — Random Free model via OpenRouter.

Copy this file, adjust to your environment, and reference it from config.yaml:

    models:
      random-free-openrouter:
        name: "Random Free (OpenRouter)"
        client_script: .dagi/model_config/my_profile.py

The script must define:
    client          — an openai.OpenAI instance

The script may optionally define:
    request_kwargs  — a dict of extra kwargs spread into chat.completions.create()
                      (e.g. temperature, max_tokens, extra_body, extra_headers).
                      Harness-managed keys (model, messages, tools, stream) always
                      take precedence over request_kwargs.
"""

import os

import openai

# ── Client construction ─────────────────────────────────────────────────────
# Full control over the openai.OpenAI() constructor — anything httpx.Client
# and the openai SDK accept can be configured here.

client = openai.OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

# ── Request-level defaults ──────────────────────────────────────────────────
# These are spread into client.chat.completions.create(**request_kwargs, ...).
# Harness-managed keys (model, messages, tools, stream) always win.

request_kwargs = {
    "model": "openrouter/free",
    "temperature": 0.7,
    "max_tokens": 4096,
}
