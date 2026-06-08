"""
LLMClient -- the abstraction over a large language model.

This is the dependency-inversion seam that keeps the loop independent of any
specific LLM vendor. The LLMDiagnoser depends on this interface, never on
OpenAI's or Anthropic's SDK directly. Swapping providers (or going from a mock
to a real model) is a one-line wiring change, with no edit to the diagnoser or
the engine.

A client's job is intentionally tiny: take a prompt, return text. All the safety
(constraining the answer to the allowlist) lives in the LLMDiagnoser's parser,
NOT here -- so no vendor client can ever widen what the system is allowed to do.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import os
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMClient(Protocol):
    """Minimal contract: given a system + user prompt, return the model's text."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        ...


class StaticLLMClient:
    """
    A test client that returns a canned response. Lets us test the LLMDiagnoser's
    prompt-building and (critically) its PARSER -- including how it handles a
    model that hallucinates an action outside the allowlist -- with no network.
    """

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self._response


class OpenAIClient:
    """
    OpenAI / Azure OpenAI client. Ready to connect: set OPENAI_API_KEY (and
    optionally OPENAI_MODEL) in the environment, then wire it in wiring.py.
    The SDK is imported lazily inside complete() so this module stays importable
    — and the tests stay dependency-free — even when the SDK isn't installed.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")  # 12-factor: from env, never hardcoded

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI  # lazy import: only needed when actually called

        client = OpenAI(api_key=self._api_key)
        resp = client.chat.completions.create(
            model=self._model,
            temperature=0,  # operational classifier, not creative writing -> deterministic
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""


class ClaudeClient:
    """
    Anthropic Claude client. Same shape as OpenAIClient, so the two are fully
    interchangeable behind LLMClient. Ready to connect: set ANTHROPIC_API_KEY
    (and optionally ANTHROPIC_MODEL) in the environment, then wire it in.
    A fast, cheap model (Haiku) is a sensible default: the job is to pick ONE
    action from a tiny allowlist, not to write prose.
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 512,
    ) -> None:
        self._model = model or os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._max_tokens = max_tokens

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        from anthropic import Anthropic  # lazy import: only needed when actually called

        client = Anthropic(api_key=self._api_key)
        resp = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0,
            system=system_prompt,  # Claude takes the system prompt as a top-level arg
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text