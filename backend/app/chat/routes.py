"""/api/chat: the discovery assistant (ADR 0014). Every route acts for the session's user only."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..auth import CurrentUser
from ..limits import device_of
from ..catalog import get_catalog
from ..db import DB
from ..models import Album
from ..schema import ChatMessage, Conversation
from . import service, tools
from .provider import ChatProvider, ProviderError, get_provider

router = APIRouter(prefix="/api/chat")


class Status(BaseModel):
    enabled: bool
    provider: str | None
    model: str | None
    maxChars: int


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    albums: list[Album]
    action: dict | None
    createdAt: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    updatedAt: datetime


class ConversationOut(ConversationSummary):
    messages: list[MessageOut]


class Ask(BaseModel):
    conversationId: str | None = Field(None, max_length=32)
    message: str = Field(max_length=service.MAX_CHARS * 2)    # trimmed, then checked against MAX_CHARS


class Answer(BaseModel):
    conversation: ConversationSummary
    messages: list[MessageOut]     # the user's message and the reply


Provider = Depends(get_provider)


def _out(m: ChatMessage) -> MessageOut:
    text = service.clean_reply(m.content) if m.role == "assistant" else m.content   # older answers may hold id notes
    return MessageOut(id=m.id, role=m.role, text=text, albums=get_catalog().get_many(m.albums or []),
                      action=m.action, createdAt=m.created_at)


def _summary(c: Conversation) -> ConversationSummary:
    return ConversationSummary(id=c.id, title=c.title, updatedAt=c.updated_at)


@router.get("/status", response_model=Status)
def status(provider: ChatProvider | None = Provider) -> Status:
    return Status(enabled=provider is not None, provider="Google Gemini" if provider else None,
                  model=provider.model if provider else None, maxChars=service.MAX_CHARS)


@router.get("/conversations", response_model=list[ConversationSummary])
def conversations(user: CurrentUser, db: DB) -> list[ConversationSummary]:
    return [_summary(c) for c in db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                                            .order_by(Conversation.updated_at.desc()).limit(30))]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def conversation(conversation_id: str, user: CurrentUser, db: DB) -> ConversationOut:
    conv = service.own_conversation(db, user, conversation_id)
    messages = service._messages(db, conv)
    return ConversationOut(**_summary(conv).model_dump(), messages=[_out(m) for m in messages])


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: CurrentUser, db: DB) -> Response:
    db.delete(service.own_conversation(db, user, conversation_id))
    return Response(status_code=204)


@router.post("", response_model=Answer)
async def ask(body: Ask, request: Request, user: CurrentUser, db: DB, provider: ChatProvider | None = Provider) -> Answer:
    """Send a message (starting a conversation when conversationId is null) and get the reply."""
    if provider is None:
        raise HTTPException(503, "The assistant is off: set GEMINI_API_KEY in backend/.env and restart the API.")
    if user.id in service.busy:
        raise HTTPException(429, "Still working on your last message.")
    service.busy.add(user.id)
    try:
        device = device_of(request)
        conv, message, state, system, history = await run_in_threadpool(service.start, db, user, body.conversationId,
                                                                        body.message, device)
        reply = await provider.respond(system, history, tools.specs(),
                                       lambda name, args: run_in_threadpool(tools.run, state, name, args), service.MAX_CALLS)
    except ProviderError as e:
        raise await run_in_threadpool(service.fail, db, message, e)
    finally:
        service.busy.discard(user.id)
    answer = await run_in_threadpool(service.finish, db, conv, message, state, reply)
    return Answer(conversation=_summary(conv), messages=[_out(message), _out(answer)])
