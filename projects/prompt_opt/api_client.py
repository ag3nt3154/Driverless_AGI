import time
import requests


class APIError(Exception):
    """Raised when an API call fails after all retries."""
    pass


class APIClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        model_name: str,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def complete(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Send a chat completion request. Returns the assistant message content."""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(self.api_url, json=payload, headers=headers, timeout=120)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
            except (requests.RequestException, KeyError, IndexError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_base ** attempt)

        raise APIError(f"API call failed after {self.max_retries} attempts: {last_error}")
