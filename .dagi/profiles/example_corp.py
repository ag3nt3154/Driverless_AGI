"""Example client profile — corporate proxy with mTLS and custom headers.

Copy this file, adjust to your environment, and reference it from config.yaml:

    models:
      corp-gpt4o:
        name: "GPT-4o (Corporate Proxy)"
        client_script: .dagi/profiles/my_profile.py

The script must define:
    client          — an openai.OpenAI instance

The script may optionally define:
    request_kwargs  — a dict of extra kwargs spread into chat.completions.create()
                      (e.g. temperature, max_tokens, extra_body, extra_headers).
                      Harness-managed keys (model, messages, tools, stream) always
                      take precedence over request_kwargs.
"""

import os

import httpx
import openai

# ── Client construction ─────────────────────────────────────────────────────
# Full control over the openai.OpenAI() constructor — anything httpx.Client
# and the openai SDK accept can be configured here.

client = openai.OpenAI(
    api_key=os.environ["CORP_API_KEY"],
    base_url="https://llm-proxy.corp.example.com/v1",
    default_headers={
        "X-Organization": "my-team",
        "X-Request-Source": "dagi",
    },
    http_client=httpx.Client(
        transport=httpx.HTTPTransport(
            local_address="0.0.0.0",
            verify="/etc/ssl/certs/corp-ca-bundle.pem",
            # cert=("/etc/ssl/client.crt", "/etc/ssl/client.key"),  # mTLS
        ),
        # proxy="http://proxy.corp.example.com:8080",
        timeout=120.0,
    ),
)

# ── Request-level defaults ──────────────────────────────────────────────────
# These are spread into client.chat.completions.create(**request_kwargs, ...).
# Harness-managed keys (model, messages, tools, stream) always win.

request_kwargs = {
    "temperature": 0.7,
    "max_tokens": 4096,
    # "extra_body": {"reasoning": {"effort": "high"}},
}
