import type { ReactNode } from "react";

/** The layout shared by the footer's pages: a title, a lead sentence, then sections. */
export function InfoPage({ title, lead, children }: { title: string; lead: ReactNode; children: ReactNode }) {
  return (
    <article className="section info-page">
      <h1 className="page-title">{title}</h1>
      <p className="info-lead">{lead}</p>
      {children}
    </article>
  );
}

export function InfoSection({ title, children, step }: { title: string; children: ReactNode; step?: number }) {
  return (
    <section className="info-section">
      {title && <h2>{step !== undefined && <span className="info-step">{step}</span>}{title}</h2>}
      {children}
    </section>
  );
}
