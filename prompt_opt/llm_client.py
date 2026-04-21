"""Thin OpenAI-compatible LLM wrapper with JSON-mode support and retry logic."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import openai


class LLMParseError(Exception):
    """Raised when JSON parsing fails after exhausting all retries."""
    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class LLMClientConfig:
    model: str
    api_key: str
    base_url: str
    temperature: float = 0.3
    max_retries: int = 3
    use_json_mode: bool = True


class LLMClient:
    def __init__(self, cfg: LLMClientConfig) -> None:
        self._client = openai.OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self._cfg = cfg

    def call_raw(self, messages: list[dict]) -> str:
        """Call the LLM and return the raw string content."""
        kwargs: dict = {
            "model": self._cfg.model,
            "messages": messages,
            "temperature": self._cfg.temperature,
        }
        if self._cfg.use_json_mode:
            try:
                kwargs["response_format"] = {"type": "json_object"}
                response = self._retry_api_call(kwargs)
                return response.choices[0].message.content or ""
            except openai.BadRequestError:
                # Model doesn't support json_object mode; fall back to prompt-only
                self._cfg = LLMClientConfig(
                    model=self._cfg.model,
                    api_key=self._cfg.api_key,
                    base_url=self._cfg.base_url,
                    temperature=self._cfg.temperature,
                    max_retries=self._cfg.max_retries,
                    use_json_mode=False,
                )
                kwargs.pop("response_format", None)
        response = self._retry_api_call(kwargs)
        return response.choices[0].message.content or ""

    def call_json(self, messages: list[dict]) -> dict:
        """
        Call LLM and return a parsed JSON dict.
        Retries up to max_retries times on parse failure, appending a clarification
        message each time. Raises LLMParseError after exhausting retries.
        """
        msgs = list(messages)
        last_raw = ""
        for attempt in range(self._cfg.max_retries + 1):
            raw = self.call_raw(msgs)
            last_raw = raw
            try:
                return json.loads(self._strip_fences(raw))
            except (json.JSONDecodeError, ValueError):
                if attempt < self._cfg.max_retries:
                    msgs.append({
                        "role": "assistant",
                        "content": raw,
                    })
                    msgs.append({
                        "role": "user",
                        "content": (
                            "Your response was not valid JSON. "
                            "Return ONLY a raw JSON object — no markdown fences, no explanation, no extra text."
                        ),
                    })
        raise LLMParseError(
            f"Failed to parse JSON after {self._cfg.max_retries + 1} attempts.",
            last_raw,
        )

    def _strip_fences(self, text: str) -> str:
        """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
        text = text.strip()
        # Match optional language tag after opening fence
        match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    def _retry_api_call(self, kwargs: dict):
        """Call the OpenAI API with exponential backoff on rate-limit errors."""
        delays = [2, 4, 8]
        for i, delay in enumerate(delays):
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.RateLimitError:
                if i == len(delays) - 1:
                    raise
                time.sleep(delay)
        return self._client.chat.completions.create(**kwargs)
