import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Album } from "../types";
import { useLibrary } from "../state/library";
import { BookmarkIcon } from "./Icons";

/** The bookmark on a cover: opens a small menu to save the album to Listen Later, any of your
 *  lists, or a new list. Filled when the album is saved anywhere. Closes on Escape or a click elsewhere. */
export function SaveMenu({ album }: { album: Album }) {
  const { isLater, toggleLater, lists, inList, toggleInList, createList } = useLibrary();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const later = isLater(album.id);
  const onLists = lists.filter((l) => inList(l.id, album.id)).length;
  const saved = later || onLists > 0;

  useEffect(() => {
    if (!open) return;
    box.current?.querySelector<HTMLElement>("input")?.focus();
    const outside = (e: PointerEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    // On the document, so Escape works even after focus leaves the menu (e.g. the Add button disables).
    const escape = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const create = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createList(name.trim(), album).catch(() => undefined);   // failures show the library banner
    setName("");
  };

  const where = [later && "Listen Later", onLists && `${onLists} ${onLists === 1 ? "list" : "lists"}`].filter(Boolean).join(" and ");
  return (
    <div className="save" ref={box}>
      <button ref={button} type="button" className={saved ? "chip on-later" : "chip"} aria-haspopup="dialog" aria-expanded={open}
        aria-label={saved ? `${album.title} is saved to ${where}. Change` : `Save ${album.title}`}
        title={saved ? `Saved to ${where}` : "Save"} onClick={() => setOpen((o) => !o)}>
        <BookmarkIcon filled={saved} />
      </button>
      {open && (
        <div className="save-pop" role="dialog" aria-label={`Save ${album.title}`}>
          <p className="save-title">Save To</p>
          <div className="save-lists">
            <label className="list-option">
              <input type="checkbox" checked={later} onChange={() => toggleLater(album)} />
              Listen Later
            </label>
            {lists.map((l) => (
              <label key={l.id} className="list-option">
                <input type="checkbox" checked={inList(l.id, album.id)} onChange={() => toggleInList(l.id, album)} />
                <span className="save-name">{l.name}</span>
              </label>
            ))}
          </div>
          <form onSubmit={create} className="list-new">
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80}
              placeholder="New list" aria-label="New list name" />
            <button className="btn btn-small" type="submit" disabled={!name.trim()}>Add</button>
          </form>
        </div>
      )}
    </div>
  );
}
