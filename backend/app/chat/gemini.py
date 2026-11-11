"""Gemini through the Google Gen AI SDK (google-genai), paid tier since 2026-11-07 (ADR 0014).

Uses generate_content with a manual tool loop: automatic function calling is off, each round's
model content goes back unchanged (it carries Gemini's thought signatures), and nothing is stored
on Google's side between requests; the conversation lives in Postgres. The SDK's own retries are
off so every retry here is counted and bounded.
"""
import asyncio
import logging
import os
import re

import httpx
from google import genai
from google.genai import errors, types

from .provider import ProviderError, Reply, RunTool, ToolSpec, Turn

log = logging.getLogger(__name__)

TIMEOUT_MS = 30_000
RETRIES = 2                 # extra attempts after a network or server error
MAX_RATE_WAIT = 10.0        # seconds; a per-minute limit asking for longer is reported, not waited out
BLOCKED = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}


def _quota(error: errors.APIError) -> tuple[bool, float | None]:
    """(daily quota used up, seconds to wait) from a 429's details, when Google includes them."""
    body = error.details if isinstance(error.details, dict) else {}
    details = (body.get("error") or body).get("details") or []
    daily, wait = False, None
    for d in details if isinstance(details, list) else []:
        if not isinstance(d, dict):
            continue
        for v in d.get("violations") or []:
            if isinstance(v, dict) and "PerDay" in str(v.get("quotaId", "")):
                daily = True
        if m := re.fullmatch(r"([\d.]+)s", str(d.get("retryDelay", ""))):
            wait = float(m[1])
    return daily, wait


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self.max_output_tokens = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "1500"))
        # Thinking level for Gemini 3 models (minimal, low, medium, high); "off" leaves it to the model.
        self.thinking = os.environ.get("GEMINI_THINKING_LEVEL", "low").strip().lower()
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))

    def _config(self, system: str, tools: list[ToolSpec], allow_tools: bool) -> types.GenerateContentConfig:
        mode = types.FunctionCallingConfigMode.AUTO if allow_tools else types.FunctionCallingConfigMode.NONE
        return types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters)
                for t in tools])],
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=mode)),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=self.max_output_tokens,
            thinking_config=None if self.thinking == "off" else types.ThinkingConfig(thinking_level=self.thinking.upper()),
        )

    async def _generate(self, contents: list[types.Content], config: types.GenerateContentConfig,
                        calls: int) -> types.GenerateContentResponse:
        """One model request with bounded retries. `calls` (made so far) goes into any error."""
        for attempt in range(RETRIES + 1):
            try:
                return await self.client.aio.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.ClientError as e:
                if e.code == 429:
                    daily, wait = _quota(e)
                    if daily:
                        raise ProviderError("quota", "The daily quota is used up", calls + 1) from e
                    if wait is not None and wait <= MAX_RATE_WAIT and attempt == 0:
                        log.info("Gemini per-minute limit; waiting %.0f s once", wait)
                        await asyncio.sleep(wait)
                        calls += 1
                        continue
                    raise ProviderError("rate", "Too many requests right now", calls + 1, wait) from e
                if e.code in (401, 403) or (e.code == 400 and "API key" in (e.message or "")):
                    raise ProviderError("config", "The Gemini API key was rejected", calls + 1) from e
                if e.code == 404:
                    raise ProviderError("config", f"Model {self.model} is not available", calls + 1) from e
                raise ProviderError("invalid", f"Gemini rejected the request ({e.code})", calls + 1) from e
            except (errors.ServerError, httpx.TransportError) as e:
                calls += 1
                if attempt == RETRIES:
                    raise ProviderError("unavailable", "Gemini is not responding", calls) from e
                log.info("Gemini unavailable (%s); retry %d", e.__class__.__name__, attempt + 1)
                await asyncio.sleep(1.0 * 2 ** attempt)
        raise AssertionError("unreachable")

    async def respond(self, system: str, history: list[Turn], tools: list[ToolSpec], run_tool: RunTool,
                      max_calls: int) -> Reply:
        contents = [types.Content(role="user" if t.role == "user" else "model", parts=[types.Part.from_text(text=t.text)])
                    for t in history]
        calls = 0
        while True:
            last = calls + 1 >= max_calls
            response = await self._generate(contents, self._config(system, tools, allow_tools=not last), calls)
            calls += 1
            feedback = response.prompt_feedback
            if feedback is not None and feedback.block_reason:
                raise ProviderError("blocked", "Gemini declined to answer that", calls)
            candidate = (response.candidates or [None])[0]
            if candidate is None or candidate.content is None:
                raise ProviderError("invalid", "Gemini sent an empty answer", calls)
            reason = candidate.finish_reason.name if candidate.finish_reason else ""
            if reason in BLOCKED:
                raise ProviderError("blocked", "Gemini declined to answer that", calls)
            parts = candidate.content.parts or []
            function_calls = [p.function_call for p in parts if p.function_call]
            if function_calls and not last:
                contents.append(candidate.content)       # as received: keeps the thought signatures
                results = []
                for call in function_calls:
                    result = await run_tool(call.name or "", dict(call.args or {}))
                    results.append(types.Part(function_response=types.FunctionResponse(
                        id=call.id, name=call.name, response=result)))
                contents.append(types.Content(role="user", parts=results))
                continue
            text = "".join(p.text for p in parts if p.text and not p.thought).strip()
            if not text:
                raise ProviderError("invalid", f"Gemini sent no text ({reason or 'no reason given'})", calls)
            return Reply(text=text, calls=calls, truncated=reason == "MAX_TOKENS")
