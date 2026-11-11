import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Artist } from "../api";
import type { Album } from "../types";
import { Cover } from "./Cover";

const DELAY_MS = 180;   // wait for a pause in typing before asking the server
const ALBUMS = 5;
const ARTISTS = 3;

export type SearchOption = { kind: "artist"; artist: Artist } | { kind: "album"; album: Album } | { kind: "all" };

/** The header search: suggests artists and albums as you type (arrow keys, Enter, Escape).
 *  Enter with nothing highlighted opens the full results. With onPick (Rate Albums You Know), choosing doesn't
 *  leave the page: the field keeps the chosen name and onPick decides what to show. onClear runs when it's emptied. */
export function SearchBox({ onPick, onClear, placeholder = "Search albums or artists", className = "search" }: {
  onPick?: (choice: SearchOption, term: string) => void;
  onClear?: () => void;
  placeholder?: string;
  className?: string;
} = {}) {
  const nav = useNavigate();
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLFormElement>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [found, setFound] = useState<{ q: string; artists: Artist[]; albums: Album[] } | null>(null);
  const request = useRef(0);

  // Suggestions for what's typed, after a short pause; older answers are ignored.
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setFound(null); return; }
    const n = ++request.current;
    const t = setTimeout(() => {
      Promise.all([api.albums({ q: term, limit: ALBUMS }), api.artists(term)]).then(
        ([albums, artists]) => n === request.current && setFound({ q: term, albums: albums.items, artists: artists.slice(0, ARTISTS) }),
        () => n === request.current && setFound(null),
      );
    }, DELAY_MS);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  const options: SearchOption[] = found
    ? [...found.artists.map((artist) => ({ kind: "artist", artist }) as SearchOption),
       ...found.albums.map((album) => ({ kind: "album", album }) as SearchOption),
       { kind: "all" }]
    : [];
  const showing = open && options.length > 0;

  const go = (o: SearchOption | undefined) => {
    const term = q.trim();
    if (onPick) {
      if (!o && !term) return;
      const choice: SearchOption = o ?? { kind: "all" };
      onPick(choice, term);
      if (choice.kind !== "all") setQ(choice.kind === "artist" ? choice.artist.name : choice.album.title);
    } else if (!o || o.kind === "all") {
      if (!term) return;
      nav(`/search?q=${encodeURIComponent(term)}`);
    } else {
      nav(o.kind === "artist" ? `/artist/${o.artist.id}` : `/album/${o.album.id}`);
      setQ("");
    }
    setOpen(false);
    setActive(-1);
    input.current?.blur();
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    go(showing && active >= 0 ? options[active] : undefined);
  };
  const keys = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!options.length) return;
      e.preventDefault();
      setOpen(true);
      // -1 is the field itself; the highlight wraps through it.
      const last = options.length - 1;
      setActive((i) => (e.key === "ArrowDown" ? (i >= last ? -1 : i + 1) : (i <= -1 ? last : i - 1)));
    } else if (e.key === "Escape") {
      if (showing) { e.preventDefault(); setOpen(false); setActive(-1); }
      else input.current?.blur();
    }
  };
  const activeIndex = active >= options.length ? -1 : active;
  const optionId = (i: number) => `${id}-opt-${i}`;

  let n = -1;
  const row = (o: SearchOption) => {
    n += 1;
    const i = n;
    const props = {
      id: optionId(i), role: "option", "aria-selected": i === activeIndex,
      className: i === activeIndex ? "suggest-option active" : "suggest-option",
      onPointerDown: (e: ReactPointerEvent) => e.preventDefault(),   // keep focus in the field
      onClick: () => go(o), onMouseMove: () => setActive(i),
    } as const;
    if (o.kind === "artist") return <li key={`ar-${o.artist.id}`} {...props}><span className="suggest-kind">Artist</span><span className="suggest-name">{o.artist.name}</span></li>;
    if (o.kind === "album") {
      return (
        <li key={`al-${o.album.id}`} {...props}>
          <span className="suggest-art" aria-hidden="true"><Cover album={o.album} /></span>
          <span className="suggest-text"><span className="suggest-name">{o.album.title}</span><span className="suggest-sub">{o.album.artist}</span></span>
        </li>
      );
    }
    return <li key="all" {...props}><span className="suggest-all">See all results for "{q.trim()}"</span></li>;
  };

  return (
    <form className={className} role="search" onSubmit={submit} ref={box}>
      <input ref={input} type="search" value={q} placeholder={placeholder} aria-label={placeholder}
        role="combobox" aria-autocomplete="list" aria-expanded={showing} aria-controls={`${id}-list`}
        aria-activedescendant={showing && activeIndex >= 0 ? optionId(activeIndex) : undefined}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(-1); if (!e.target.value) onClear?.(); }}
        onFocus={() => setOpen(true)} onKeyDown={keys} />
      {showing && (
        <ul className="suggest" id={`${id}-list`} role="listbox" aria-label="Suggestions">
          {options.map(row)}
        </ul>
      )}
    </form>
  );
}
