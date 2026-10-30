"""Chat transports.

The shipped transport talks to the Nebius Token Factory inference API
(OpenAI-compatible). Everything else in ProofCrew depends only on the
``complete(model, system, user) -> str`` shape, so tests can inject a fake
transport without any network or SDK.
"""
from __future__ import annotations

from typing import Protocol


class ChatTransport(Protocol):
    def complete(self, model: str, system: str, user: str) -> str:
        ...


class TokenFactoryTransport:
    """Runtime calls to Nebius Token Factory — this is what makes ProofCrew
    'run on Nebius' under the hackathon rules."""

    def __init__(self, api_key: str, base_url: str):
        # Imported lazily so unit tests and the stdlib-only receipt verifier
        # never need the SDK installed.
        from openai import OpenAI

        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=180.0,
            max_retries=1,
        )

    def complete(self, model: str, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""
