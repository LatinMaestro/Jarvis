from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from .config import AssistantConfig


class GeminiError(RuntimeError):
    pass


class GeminiRateLimitError(GeminiError):
    pass


@dataclass
class GeminiClient:
    config: AssistantConfig

    async def generate(self, prompt: str) -> str:
        import aiohttp

        if not self.config.gemini_ready():
            raise GeminiError("Gemini is disabled or not configured")

        model = urllib.parse.quote(self.config.model, safe="")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={urllib.parse.quote(self.config.gemini_api_key, safe='')}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.85,
                "topP": 0.9,
                "maxOutputTokens": max(128, min(1024, self.config.max_response_chars // 3)),
            },
        }

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status in {429, 503}:
                    raise GeminiRateLimitError(f"Gemini free-tier limit response: {response.status}")
                if response.status >= 400:
                    raise GeminiError(f"Gemini response status: {response.status}")
                data = await response.json()

        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text", "")) for part in parts)
        except Exception as exc:  # noqa: BLE001 - keep provider parsing failure graceful.
            raise GeminiError("Gemini response did not include text") from exc

        if not text.strip():
            raise GeminiError("Gemini returned an empty response")
        return text.strip()
