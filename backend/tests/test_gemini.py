"""The Gemini adapter against a stubbed SDK client: the tool loop, retries and quota handling, with no
network. test_gemini_live.py makes one real request, only when asked to."""
import asyncio

import httpx
import pytest
from google.genai import errors, types

from app.chat import gemini
from app.chat.gemini import GeminiProvider
from app.chat.provider import ProviderError, ToolSpec, Turn

TOOLS = [ToolSpec("search_catalog", "Find albums", {"type": "object", "properties": {"query": {"type": "string"}}})]


def response(*parts: types.Part, finish="STOP") -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=list(parts)), finish_reason=types.FinishReason(finish))])


def text(t: str) -> types.Part:
    return types.Part(text=t)


def call(name="search_catalog", args=None, id="call-1") -> types.Part:
    return types.Part(function_call=types.FunctionCall(id=id, name=name, args=args or {"query": "radiohead"}),
                      thought_signature=b"signature")


def quota_error(quota_id: str, delay: str | None = None) -> errors.ClientError:
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]}]
    if delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota", "details": details}})


class Stub:
    """Stands in for client.aio.models: returns (or raises) the scripted items in order."""

    def __init__(self, *script):
        self.script, self.requests = list(script), []

    async def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def provider(monkeypatch):
    p = GeminiProvider("test-key", model="gemini-test")
    real_sleep = asyncio.sleep
    monkeypatch.setattr(gemini.asyncio, "sleep", lambda seconds: real_sleep(0))   # no real waiting in tests
    return p


def run(provider, stub, max_calls=4, tools_seen=None):
    provider.client = type("C", (), {"aio": type("A", (), {"models": stub})()})()

    async def run_tool(name, args):
        (tools_seen if tools_seen is not None else []).append((name, args))
        return {"albums": [{"title": "Kid A"}]}
    return asyncio.run(provider.respond("system", [Turn("user", "hi")], TOOLS, run_tool, max_calls))


def test_tool_calls_run_and_their_results_go_back_with_the_signature(provider):
    stub, seen = Stub(response(call()), response(text("Try Kid A."))), []
    reply = run(provider, stub, tools_seen=seen)
    assert reply.text == "Try Kid A." and reply.calls == 2 and seen == [("search_catalog", {"query": "radiohead"})]
    second = stub.requests[1]["contents"]
    assert second[1].parts[0].thought_signature == b"signature"                 # model turn passed back as received
    result = second[2].parts[0].function_response
    assert result.id == "call-1" and result.name == "search_catalog" and result.response == {"albums": [{"title": "Kid A"}]}
    config = stub.requests[0]["config"]
    assert config.automatic_function_calling.disable and config.max_output_tokens == provider.max_output_tokens
    assert config.tools[0].function_declarations[0].name == "search_catalog"


def test_the_last_allowed_request_turns_tools_off(provider):
    stub = Stub(response(call()), response(call(id="call-2")), response(text("Done.")))
    reply = run(provider, stub, max_calls=3)
    assert reply.calls == 3
    modes = [r["config"].tool_config.function_calling_config.mode for r in stub.requests]
    assert modes == [types.FunctionCallingConfigMode.AUTO] * 2 + [types.FunctionCallingConfigMode.NONE]


def test_thoughts_are_not_part_of_the_reply_and_truncation_is_flagged(provider):
    reply = run(provider, Stub(response(types.Part(text="hidden", thought=True), text("Visible"), finish="MAX_TOKENS")))
    assert reply.text == "Visible" and reply.truncated


def test_a_used_up_daily_quota_is_not_retried(provider):
    stub = Stub(quota_error("GenerateRequestsPerDayPerProjectPerModel-FreeTier", "40s"))
    with pytest.raises(ProviderError) as e:
        run(provider, stub)
    assert e.value.kind == "quota" and e.value.calls == 1 and len(stub.requests) == 1


def test_a_short_per_minute_limit_is_retried_once(provider):
    stub = Stub(quota_error("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "2s"), response(text("ok")))
    assert run(provider, stub).text == "ok" and len(stub.requests) == 2
    stub = Stub(*[quota_error("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "2s")] * 2)
    with pytest.raises(ProviderError) as e:
        run(provider, stub)
    assert e.value.kind == "rate" and len(stub.requests) == 2
    stub = Stub(quota_error("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "45s"))
    with pytest.raises(ProviderError) as e:
        run(provider, stub)
    assert e.value.kind == "rate" and e.value.retry_after == 45 and len(stub.requests) == 1


def test_server_and_network_errors_get_bounded_retries(provider):
    stub = Stub(errors.ServerError(503, {"error": {"code": 503, "message": "overloaded"}}),
                httpx.ConnectError("down"), response(text("ok")))
    assert run(provider, stub).text == "ok"
    stub = Stub(*[errors.ServerError(500, {"error": {"code": 500}})] * (gemini.RETRIES + 1))
    with pytest.raises(ProviderError) as e:
        run(provider, stub)
    assert e.value.kind == "unavailable" and e.value.calls == gemini.RETRIES + 1


@pytest.mark.parametrize("error,kind", [
    (errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid"}}), "config"),
    (errors.ClientError(404, {"error": {"code": 404, "message": "model not found"}}), "config"),
    (errors.ClientError(400, {"error": {"code": 400, "message": "bad schema"}}), "invalid"),
])
def test_client_errors(provider, error, kind):
    with pytest.raises(ProviderError) as e:
        run(provider, Stub(error))
    assert e.value.kind == kind


def test_blocked_and_empty_answers(provider):
    for item in (response(text("x"), finish="SAFETY"),
                 types.GenerateContentResponse(prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason="SAFETY")),
                 response(finish="STOP")):
        with pytest.raises(ProviderError) as e:
            run(provider, Stub(item))
        assert e.value.kind in ("blocked", "invalid")
