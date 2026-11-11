import { Fragment, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type ChatAction, type ChatMessage, type ConversationSummary } from "../api";
import { AlbumCard } from "../components/AlbumCard";
import { ErrorNote, Loading } from "../components/Notice";
import { useFetch } from "../hooks/useFetch";
import { useLibrary } from "../state/library";

const CHAT_KEY = "inrotation.chat";
const SUGGESTIONS = [
  "Recommend 10 albums like my favorites",
  "I want to discover more dream pop",
  "Something like Radiohead, but less mainstream",
  "Albums from the 1990s I might enjoy",
  "Show me something completely different",
];

function stored(): string | null {
  try {
    return localStorage.getItem(CHAT_KEY);
  } catch {
    return null;
  }
}

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(CHAT_KEY, id);
    else localStorage.removeItem(CHAT_KEY);
  } catch {
    // Private windows can block storage; the conversation then lasts for this visit only.
  }
}

/** **bold** inside a line; everything else stays plain text (React escapes it). */
function inline(line: string): ReactNode[] {
  return line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part);
}

/** The assistant's plain text: paragraphs and "-" lists, the only formatting it is asked to use. */
function Rich({ text }: { text: string }) {
  const blocks = text.replace(/^#+\s*/gm, "").split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, b) => {
        const lines = block.split("\n").filter((l) => l.trim());
        const bullet = /^\s*(?:[-*•]|\d+\.)\s+/;
        if (lines.length && lines.every((l) => bullet.test(l))) {
          return <ul key={b}>{lines.map((l, i) => <li key={i}>{inline(l.replace(bullet, ""))}</li>)}</ul>;
        }
        return <p key={b}>{lines.map((l, i) => <Fragment key={i}>{i > 0 && <br />}{inline(l)}</Fragment>)}</p>;
      })}
    </>
  );
}

function Typing() {
  return (
    <div className="msg msg-assistant" role="status" aria-label="The assistant is thinking">
      <span className="typing" aria-hidden="true"><span /><span /><span /></span>
    </div>
  );
}

export default function Ask() {
  const { reload, rated } = useLibrary();
  const status = useFetch(() => api.chatStatus(), []);
  const [conversationId, setConversationId] = useState<string | null>(stored);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<{ text: string; retry: string | null } | null>(null);
  const [undone, setUndone] = useState<Set<number>>(new Set());
  const [opening, setOpening] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const created = useRef<string | null>(null);
  const enabled = status.data?.enabled ?? false;
  const maxChars = status.data?.maxChars ?? 1000;

  const loadHistory = () => api.conversations().then(setHistory, () => undefined);

  useEffect(() => {
    loadHistory();
  }, []);

  useEffect(() => {
    if (!conversationId || conversationId === created.current) return;   // a conversation just started here is already on screen
    let live = true;
    setOpening(true);
    api.conversation(conversationId).then(
      (c) => live && setMessages(c.messages),
      (e) => {
        if (!live) return;
        if (e instanceof ApiError && e.status === 404) {
          setConversationId(null);
          remember(null);
        } else setError({ text: e.message, retry: null });
      },
    ).finally(() => live && setOpening(false));
    return () => {
      live = false;
    };
  }, [conversationId]);

  useEffect(() => {
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    end.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "end" });
  }, [messages, pending]);

  const open = (id: string | null) => {
    setError(null);
    setUndone(new Set());
    setMessages([]);
    setConversationId(id);
    remember(id);
    input.current?.focus();
  };

  const send = async (text: string) => {
    text = text.trim();
    if (!text || pending) return;
    setError(null);
    setPending(text);
    setDraft("");
    try {
      const answer = await api.ask(conversationId, text);
      setMessages((ms) => [...ms, ...answer.messages]);
      if (answer.conversation.id !== conversationId) {
        created.current = answer.conversation.id;
        setConversationId(answer.conversation.id);
        remember(answer.conversation.id);
      }
      if (answer.messages.some((m) => m.action)) await reload();
      loadHistory();
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      // Retrying makes sense after a hiccup, not after a limit or a refused message.
      const retry = status === 0 || status >= 500 ? text : null;
      setError({ text: e instanceof Error ? e.message : "Something went wrong.", retry });
      if (status === 422 || status === 0) setDraft(text);
    } finally {
      setPending(null);
    }
  };

  const undo = async (message: ChatMessage, action: ChatAction) => {
    try {
      if (action.createdList && action.listId !== null) await api.deleteList(action.listId);
      else
        for (const id of action.albumIds) {
          await (action.listId === null ? api.setLater(id, false) : api.setInList(action.listId, id, false));
        }
      setUndone((u) => new Set(u).add(message.id));
    } catch {
      setError({ text: "Couldn't undo that. Check your library.", retry: null });
    }
    await reload();
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(draft);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(draft);
    }
  };

  const empty = messages.length === 0 && !pending && !opening;
  return (
    <section className="section ask">
      <div className="ask-head">
        <div>
          <h1 className="page-title">Ask</h1>
          <p className="muted">Tell it what you're in the mood for. Picks come from In Rotation's listening data, shaped by your ratings.</p>
        </div>
        <div className="ask-tools">
          {history.length > 0 && (
            <details className="ask-history">
              <summary className="btn btn-quiet btn-small">Earlier Chats</summary>
              <ul>
                {history.map((c) => (
                  <li key={c.id}>
                    <button type="button" className={c.id === conversationId ? "active" : ""} onClick={(e) => {
                      (e.currentTarget.closest("details") as HTMLDetailsElement).open = false;
                      open(c.id);
                    }}>{c.title}</button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <button type="button" className="btn btn-small" onClick={() => open(null)} disabled={!!pending || (empty && !conversationId)}>
            New Chat
          </button>
        </div>
      </div>

      {status.error && <ErrorNote error={status.error} />}
      {status.data && !enabled && (
        <p className="notice" role="alert">
          {import.meta.env.DEV
            ? `The assistant is off. Add a Gemini API key as GEMINI_API_KEY in backend/.env and restart the API (README, "The assistant").`
            : "Ask isn't available right now. Everything else on the site works as usual."}
        </p>
      )}

      <div className="chat" aria-live="polite">
        {opening && <Loading label="Opening the conversation" />}
        {empty && enabled && (
          <div className="chat-empty">
            <p className="chat-empty-title">Where do you want to go?</p>
            {rated.length === 0 && (
              <p className="muted">Tip: <Link to="/start">rate a few albums</Link> first and the suggestions will fit you better.</p>
            )}
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="filter" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg msg-${m.role}`}>
            <div className="msg-text">{m.role === "assistant" ? <Rich text={m.text} /> : <p>{m.text}</p>}</div>
            {m.albums.length > 0 && (
              <div className="chat-albums">
                {m.albums.map((a) => <AlbumCard key={a.id} album={a} detail={a.year ? String(a.year) : null} />)}
              </div>
            )}
            {m.action && m.action.albumIds.length > 0 && (
              <p className="msg-action">
                {undone.has(m.id) ? "Undone." : (
                  <>
                    Saved to <Link to={m.action.listId !== null ? `/library/lists/${m.action.listId}` : "/library/listen-later"}><strong>{m.action.listName}</strong></Link>.
                    <button type="button" className="btn btn-quiet btn-small" onClick={() => undo(m, m.action!)}>Undo</button>
                  </>
                )}
              </p>
            )}
          </div>
        ))}
        {pending && (
          <>
            <div className="msg msg-user"><div className="msg-text"><p>{pending}</p></div></div>
            <Typing />
          </>
        )}
        {error && (
          <p className="notice chat-error" role="alert">
            {error.text}
            {error.retry && <button type="button" className="btn btn-quiet btn-small" onClick={() => send(error.retry!)}>Try Again</button>}
          </p>
        )}
        <div ref={end} />
      </div>

      <form className="composer" onSubmit={submit}>
        <label htmlFor="ask-input" className="visually-hidden">Message the assistant</label>
        <textarea id="ask-input" ref={input} value={draft} rows={1} maxLength={maxChars} disabled={!enabled}
          placeholder={enabled ? "What are you in the mood for?" : "The assistant is off"}
          onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} />
        <button type="submit" className="btn" disabled={!enabled || !!pending || !draft.trim()}>Send</button>
        {draft.length > maxChars * 0.8 && <span className="composer-count">{maxChars - draft.length} left</span>}
      </form>
    </section>
  );
}
