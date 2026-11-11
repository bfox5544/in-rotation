import { useState, type FormEvent } from "react";
import type { Album } from "../types";
import { useLibrary } from "../state/library";

/** "Add to list" on the album page: tick the user's lists, or start a new one with this album. */
export function ListMenu({ album }: { album: Album }) {
  const { lists, inList, toggleInList, createList } = useLibrary();
  const [name, setName] = useState("");
  const count = lists.filter((l) => inList(l.id, album.id)).length;
  const create = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    createList(name.trim(), album).catch(() => undefined);   // failures show the library banner
    setName("");
  };
  return (
    <details className="list-menu">
      <summary className="btn btn-quiet">{count > 0 ? `On ${count} ${count === 1 ? "List" : "Lists"}` : "Add to List"}</summary>
      <div className="list-menu-panel">
        {lists.map((l) => (
          <label key={l.id} className="list-option">
            <input type="checkbox" checked={inList(l.id, album.id)} onChange={() => toggleInList(l.id, album)} />
            {l.name}
          </label>
        ))}
        <form onSubmit={create} className="list-new">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80}
            placeholder="New list" aria-label="New list name" />
          <button className="btn" type="submit" disabled={!name.trim()}>Add</button>
        </form>
      </div>
    </details>
  );
}
