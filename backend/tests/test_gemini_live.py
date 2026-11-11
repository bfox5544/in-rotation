"""One real Gemini request (costs a fraction of a cent). Skipped unless asked for:

    INROTATION_LIVE_GEMINI=1 pytest tests/test_gemini_live.py      # with GEMINI_API_KEY in backend/.env
"""
import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from app.chat.gemini import GeminiProvider
from app.chat.provider import ToolSpec, Turn

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
pytestmark = pytest.mark.skipif(not (os.environ.get("INROTATION_LIVE_GEMINI") == "1" and os.environ.get("GEMINI_API_KEY")),
                                reason="live Gemini test: set INROTATION_LIVE_GEMINI=1 and GEMINI_API_KEY")


def test_connection_and_function_calling():
    provider = GeminiProvider(os.environ["GEMINI_API_KEY"], os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite")
    asked = []

    async def run_tool(name, args):
        asked.append((name, args))
        return {"albums": [{"id": "a1", "title": "Kid A", "artist": "Radiohead", "year": 2000}]}
    tools = [ToolSpec("search_catalog", "Find albums in the catalog by title or artist.",
                      {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})]
    reply = asyncio.run(provider.respond("Use search_catalog to look albums up before answering.",
                                         [Turn("user", "Which Radiohead albums do you have?")], tools, run_tool, 3))
    assert asked and asked[0][0] == "search_catalog" and "radiohead" in asked[0][1]["query"].lower()
    assert "Kid A" in reply.text and reply.calls == 2
