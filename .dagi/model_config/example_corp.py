"""Example client-script model — Random Free model via OpenRouter.

A .py file in .dagi/model_config/ is a model on its own; no YAML is needed.
The filename (without .py) is the model ID, so this file is selectable as:

    default_model: example_corp        # in .dagi/config.yaml

Use this when the OpenAI client needs arguments a YAML entry can't express:
mTLS certificates, custom transports, proxies, guardrail headers, etc.

The script must define:
    client          — an openai.OpenAI instance (sync; AsyncOpenAI is rejected
                      because dagi calls the API synchronously)

The script may optionally define:
    request_kwargs  — a dict of extra kwargs spread into chat.completions.create()
                      (e.g. model, temperature, max_tokens, extra_headers).
                      request_kwargs["model"] is the model name sent to the API.
                      Other harness-managed keys (messages, tools, stream) always
                      take precedence.
    dagi_config     — a dict of the same settings a YAML model entry accepts:
                      name, model, context_window, reserve_tokens,
                      keep_recent_tokens, max_output_tokens, thinking, stream,
                      cache_prompt, supports_images, ...
                      Keep it a plain literal so the model picker can read the
                      display name without executing the script.

Files starting with "_" are ignored, so shared helpers can live next to the
scripts (e.g. _corp_common.py). If a same-named .yaml exists, the YAML entry
wins (it can still point at a script via `client_script:`).
"""

import os

import openai

# ── Client construction ─────────────────────────────────────────────────────
# Full control over the openai.OpenAI() constructor — anything httpx and the
# openai SDK accept can be configured here. For example, mTLS + guardrail
# headers behind a corporate gateway:
#
#   import ssl, httpx
#   ctx = ssl.create_default_context(cafile="C:/certs/corp-ca.pem")
#   ctx.load_cert_chain("C:/certs/client.pem", "C:/certs/client.key")
#   client = openai.OpenAI(
#       api_key=os.environ["CORP_API_KEY"],
#       base_url="https://llm-gateway.corp.example.com/v1",
#       default_headers={"ENABLE-GUARDRAILS-INPUT-CHECK": "false"},
#       http_client=openai.DefaultHttpxClient(
#           transport=httpx.HTTPTransport(verify=ctx, retries=2),
#           timeout=120.0,
#       ),
#   )

client = openai.OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

# ── Request-level defaults ──────────────────────────────────────────────────
# Spread into client.chat.completions.create(**request_kwargs, ...).

request_kwargs = {
    "model": "openrouter/free",
    "temperature": 0.7,
    "max_tokens": 4096,
}

# ── dagi settings (optional) ────────────────────────────────────────────────

dagi_config = {
    "name": "Example Corp (OpenRouter Free)",
    "context_window": 128000,
}
