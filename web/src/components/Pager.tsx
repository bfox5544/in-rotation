import { ArrowIcon } from "./Icons";

/** Numbered pages between previous and next arrows. `page` is 1-based. Renders nothing for a single page. */
export function Pager({ page, pages, onPage, label = "Pages" }: {
  page: number; pages: number; onPage: (page: number) => void; label?: string;
}) {
  if (pages <= 1) return null;
  return (
    <nav className="pager" aria-label={label}>
      <button type="button" className="btn btn-quiet btn-small pager-arrow" disabled={page <= 1} onClick={() => onPage(page - 1)}
        aria-label="Previous page" title="Previous page">
        <ArrowIcon direction="left" />
      </button>
      <ol className="pager-pages">
        {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
          <li key={n}>
            <button type="button" className={n === page ? "pager-page active" : "pager-page"}
              aria-current={n === page ? "page" : undefined} aria-label={`Page ${n}`} onClick={() => onPage(n)}>
              {n}
            </button>
          </li>
        ))}
      </ol>
      <button type="button" className="btn btn-quiet btn-small pager-arrow" disabled={page >= pages} onClick={() => onPage(page + 1)}
        aria-label="Next page" title="Next page">
        <ArrowIcon direction="right" />
      </button>
    </nav>
  );
}
