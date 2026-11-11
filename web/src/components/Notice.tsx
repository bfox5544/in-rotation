import { ApiError } from "../api";

export function ErrorNote({ error }: { error: Error }) {
  const text = error instanceof ApiError && error.status === 0 ? error.message : "Something went wrong loading this. Try again in a moment.";
  return <p className="notice" role="alert">{text}</p>;
}

export function Loading({ label = "Loading albums" }: { label?: string }) {
  return <p className="muted" role="status">{label}...</p>;
}

/** Gray tiles in the shape of the album grid while albums load, so the page doesn't jump. */
export function SkeletonGrid({ count = 12, label = "Loading albums" }: { count?: number; label?: string }) {
  return (
    <div className="grid skeleton" role="status" aria-label={`${label}...`}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-card" aria-hidden="true">
          <span className="skel skel-cover" />
          <span className="skel skel-line" />
          <span className="skel skel-line short" />
        </div>
      ))}
    </div>
  );
}

/** An album or artist page's shape while it loads: a cover and a few lines, or a title over a grid. */
export function SkeletonDetail({ label = "Loading album" }: { label?: string }) {
  return (
    <section className="section">
      <div className="detail skeleton" role="status" aria-label={`${label}...`}>
        <span className="skel skel-cover" aria-hidden="true" />
        <div aria-hidden="true">
          <span className="skel skel-title" />
          <span className="skel skel-line short" />
          <span className="skel skel-line" />
          <span className="skel skel-line" />
        </div>
      </div>
    </section>
  );
}

export function SkeletonPage({ label, count = 12 }: { label: string; count?: number }) {
  return (
    <section className="section">
      <span className="skel skel-title skeleton" aria-hidden="true" />
      <SkeletonGrid count={count} label={label} />
    </section>
  );
}
