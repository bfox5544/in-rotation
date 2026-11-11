import { useEffect, useId, useRef, useState } from "react";
import { api, type BrowseOptions } from "../api";
import { useFetch } from "../hooks/useFetch";
import { activeCount, count, countryName, toQuery, type FilterKey, type Filters } from "../lib/filters";
import { titleCase } from "../lib/text";
import { CloseIcon } from "./Icons";

interface Option { value: string; label: string; hint?: string }

/** Type to search, pick from the list; the choice shows as a removable pill. */
function SearchPicker({ label, placeholder, selected, onSelect, search, searchEmpty = false }: {
  label: string;
  placeholder: string;
  selected: Option | null;
  onSelect: (option: Option | null) => void;
  search: (q: string) => Promise<Option[]>;
  /** Offer suggestions before anything is typed. */
  searchEmpty?: boolean;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setQuery(text.trim()), 200);
    return () => clearTimeout(t);
  }, [text]);
  const results = useFetch(() => search(query), [query], open && (searchEmpty || query.length > 0));
  const options = results.data ?? [];
  useEffect(() => setActive(0), [results.data]);

  const pick = (o: Option) => {
    onSelect(o);
    setText("");
    setOpen(false);
  };

  if (selected) {
    return (
      <div className="filter-field">
        <span className="filter-label" id={`${id}-label`}>{label}</span>
        <div className="picked" aria-labelledby={`${id}-label`}>
          <span>{selected.label}</span>
          <button type="button" className="chip" aria-label={`Clear ${label.toLowerCase()}`} onClick={() => onSelect(null)}><CloseIcon /></button>
        </div>
      </div>
    );
  }
  const listId = `${id}-list`;
  const showList = open && options.length > 0;
  return (
    <div className="filter-field">
      <label className="filter-label" htmlFor={id}>{label}</label>
      <input id={id} type="search" value={text} placeholder={placeholder} autoComplete="off"
        role="combobox" aria-expanded={showList} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={showList ? `${listId}-${active}` : undefined}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
            if (options.length) setActive((a) => (a + (e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length);
          } else if (e.key === "Enter") {
            e.preventDefault();
            // Only once the list has caught up with what's typed: "jazz" + Enter mustn't pick the
            // first of the suggestions shown before typing (Rock).
            if (showList && text.trim() === query && !results.loading) pick(options[active]);
          } else if (e.key === "Escape" && showList) {
            e.preventDefault();       // close the list, not the dialog
            setOpen(false);
          }
        }} />
      {showList && (
        <ul id={listId} className="picker-list" role="listbox" aria-label={label}>
          {options.map((o, i) => (
            <li key={o.value} id={`${listId}-${i}`} role="option" aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setActive(i)} onClick={() => pick(o)}>
              <span>{o.label}</span>
              {o.hint && <span className="picker-hint">{o.hint}</span>}
            </li>
          ))}
        </ul>
      )}
      {open && results.data && options.length === 0 && query && <p className="picker-empty">No matches</p>}
    </div>
  );
}

function Select({ label, value, any, options, onChange, disabled }: {
  label: string;
  value: string | undefined;
  any: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="filter-field">
      <label className="filter-label" htmlFor={id}>{label}</label>
      <select id={id} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {any && <option value="">{any}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

const genreOptions = (q: string) =>
  api.genreSearch(q).then((gs) => gs.map((g) => ({
    value: g.name,
    label: titleCase(g.name),
    hint: `${g.parent ? `in ${titleCase(g.parent)}, ` : ""}${count(g.albums)} albums`,
  })));

/** Small removable chips for the filters in effect, labelled the way the modal shows them. */
export function ActiveFilters({ filters, options, onRemove }: {
  filters: Filters;
  options: BrowseOptions | null;
  onRemove: (key: FilterKey) => void;
}) {
  const label = (k: FilterKey, v: string): string => {
    switch (k) {
      case "genre": return titleCase(v);
      case "decade": return `${v}s`;
      case "popularity": return options?.popularity.find((p) => p.key === v)?.label ?? titleCase(v.replace(/_/g, " "));
      case "country": return countryName(v);
      case "type": return options?.types.find((t) => t.key === v)?.label ?? titleCase(v);
      case "length": return options?.lengths.find((l) => l.key === v)?.label ?? titleCase(v.replace(/_/g, " "));
      default: return v;
    }
  };
  const keys = (Object.keys(filters) as FilterKey[]).filter((k) => k !== "sort" && filters[k]);
  return (
    <ul className="active-filters" aria-label="Active filters">
      {keys.map((k) => (
        <li key={k} className="filter-chip">
          <span>{label(k, filters[k]!)}</span>
          <button type="button" aria-label={`Remove ${label(k, filters[k]!)}`} onClick={() => onRemove(k)}><CloseIcon /></button>
        </li>
      ))}
    </ul>
  );
}

/**
 * Catalog filters (ADR 0015) in a modal dialog. Changes are a draft until applied. On Browse Albums the
 * apply button shows how many albums the draft matches. For You (ADR 0026) offers Genre, Decade, Length and
 * Album Type: no Popularity (its How Well Known slider covers it), Exact Year or Country, and no count, since
 * its list depends on your taste.
 */
export function FilterModal({ open, filters, onApply, onClose, forYou = false }: {
  open: boolean;
  filters: Filters;
  onApply: (filters: Filters) => void;
  onClose: () => void;
  forYou?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState<Filters>(filters);
  const [matches, setMatches] = useState<number | null>(null);
  const options = useFetch<BrowseOptions>(api.browseOptions, [], open);

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) {
      setDraft(filters);
      d.showModal();
    } else if (!open && d.open) d.close();
  }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps

  // How many albums the draft matches, shown on the apply button.
  useEffect(() => {
    if (!open || forYou) return;
    setMatches(null);
    let live = true;
    const t = setTimeout(() => {
      api.albums({ ...toQuery(draft), limit: 1 }).then((page) => live && setMatches(page.total), () => live && setMatches(null));
    }, 250);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [open, JSON.stringify(draft)]);   // eslint-disable-line react-hooks/exhaustive-deps

  const set = (changes: Filters) => setDraft((d) => ({ ...d, ...changes }));
  const o = options.data;

  return (
    <dialog ref={dialog} className="filter-modal" aria-labelledby="filter-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onMouseDown={(e) => e.target === dialog.current && onClose()}>
      <form method="dialog" className="filter-panel" onSubmit={(e) => {
        e.preventDefault();
        onApply(draft);
      }}>
        <header className="filter-head">
          <h2 id="filter-title">{forYou ? "Filter Your Picks" : "Filter Albums"}</h2>
          <button type="button" className="chip" aria-label="Close without applying" onClick={onClose}><CloseIcon /></button>
        </header>
        <div className="filter-body">
          <SearchPicker label="Genre" placeholder="Search genres and subgenres" searchEmpty
            selected={draft.genre ? { value: draft.genre, label: titleCase(draft.genre) } : null}
            onSelect={(g) => set({ genre: g?.value })} search={genreOptions} />
          <div className="filter-pair">
            <Select label="Decade" any="Any Time" value={draft.decade} disabled={!forYou && !!draft.year}
              onChange={(v) => set({ decade: v || undefined })}
              options={(o?.decades ?? []).map((d) => ({ value: String(d.decade), label: `${d.decade}s` }))} />
            {forYou ? (
              <Select label="Length" any="Any Length" value={draft.length}
                onChange={(v) => set({ length: v || undefined })}
                options={(o?.lengths ?? []).map((l) => ({ value: l.key, label: l.label }))} />
            ) : (
              <div className="filter-field">
                <label className="filter-label" htmlFor="filter-year">Exact Year</label>
                <input id="filter-year" type="number" inputMode="numeric" min={1900} max={2100} placeholder="Any"
                  value={draft.year ?? ""} onChange={(e) => set({ year: e.target.value || undefined })} />
              </div>
            )}
          </div>
          {!forYou && (
            <Select label="Popularity" any="Any" value={draft.popularity}
              onChange={(v) => set({ popularity: v || undefined })}
              options={(o?.popularity ?? []).map((p) => ({
                value: p.key,
                label: `${p.label}: ${p.min === null ? `under ${count((p.max ?? 0) + 1)}` : p.max === null ? `${count(p.min)}+` : `${count(p.min)} to ${count(p.max + 1)}`} listeners`,
              }))} />
          )}
          {!forYou && (
            <Select label="Country" any="Anywhere" value={draft.country}
              onChange={(v) => set({ country: v || undefined })}
              options={(o?.countries ?? [])
                .map((c) => ({ value: c.code, label: countryName(c.code) }))
                .sort((a, b) => a.label.localeCompare(b.label))} />
          )}
          <Select label="Album Type" any="Any Type" value={draft.type}
            onChange={(v) => set({ type: v || undefined })}
            options={(o?.types ?? []).map((t) => ({ value: t.key, label: t.label }))} />
          {options.error && <p className="notice" role="alert">Couldn't load the filter choices. Try again in a moment.</p>}
        </div>
        <footer className="filter-foot">
          <button type="button" className="btn btn-quiet" disabled={activeCount(draft) === 0} onClick={() => setDraft({ sort: draft.sort })}>
            Clear All
          </button>
          {forYou ? (
            <button type="submit" className="btn">Show Picks</button>
          ) : (
            <button type="submit" className="btn" disabled={matches === 0}>
              {matches === null ? "Show Albums" : matches === 0 ? "No Albums Match" : `Show ${count(matches)} ${matches === 1 ? "Album" : "Albums"}`}
            </button>
          )}
        </footer>
      </form>
    </dialog>
  );
}
