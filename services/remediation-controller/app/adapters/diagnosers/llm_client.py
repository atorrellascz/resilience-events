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
    Stub for Azure OpenAI / OpenAI. Not wired to the network yet -- it documents
    exactly where the SDK call goes, so enabling it later is a small, contained
    change. Constructing it does nothing expensive; it raises only if you
    actually call complete() before implementing it.
    """

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key  # injected from env/secret later; never hardcoded

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # Later:
        #   from openai import OpenAI            (or AzureOpenAI)
        #   client = OpenAI(api_key=self._api_key)
        #   resp = client.chat.completions.create(
        #       model=self._model,
        #       messages=[{"role": "system", "content": system_prompt},
        #                 {"role": "user", "content": user_prompt}],
        #       temperature=0,          # deterministic-ish for an operational tool
        #   )
        #   return resp.choices[0].message.content
        raise NotImplementedError("OpenAIClient.complete is a stub; wire the SDK to enable it")


class ClaudeClient:
    """
    Stub for Anthropic Claude. Same shape as OpenAIClient so the two are fully
    interchangeable behind LLMClient.
    """

    def __init__(self, model: str = "claude-3-5-sonnet", api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # Later:
        #   from anthropic import Anthropic
        #   client = Anthropic(api_key=self._api_key)
        #   resp = client.messages.create(
        #       model=self._model,
        #       max_tokens=512,
        #       system=system_prompt,
        #       messages=[{"role": "user", "content": user_prompt}],
        #   )
        #   return resp.content[0].text
        raise NotImplementedError("ClaudeClient.complete is a stub; wire the SDK to enable it")