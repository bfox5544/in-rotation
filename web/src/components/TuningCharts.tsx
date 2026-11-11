import { useState, type CSSProperties, type ReactNode } from "react";

/**
 * Small charts for How Recommendations Work: how each engine setting was chosen (docs/experiments.md).
 * Plain HTML and CSS like the Insights charts, with an SVG only for line strokes. The chosen setting is drawn in
 * --chart-pick, other options in the neutral --chart-rest, and a second series in --chart-alt. Every mark shows its
 * value on hover or focus. Each sits in a TuneQuestion: question, answer, two sentences, chart (owner choice C). Styles: .tune-* in styles.css.
 */

export interface Row { label: string; value: number; chosen?: boolean; detail?: string; spread?: number }

const pct = (v: number, min: number, max: number) => `${((v - min) / (max - min)) * 100}%`;
/** Tooltips near either end open inward, so they never run past the chart. */
const side = (v: number, min: number, max: number) => {
  const f = (v - min) / (max - min);
  return f < 0.3 ? "tune-tip start" : f > 0.7 ? "tune-tip end" : "tune-tip";
};

/** One setting as a visitor's question, a short answer, two plain sentences and a simple chart (owner choice C). */
export function TuneQuestion({ question, answer, children, chart }: { question: string; answer: string; children: ReactNode; chart: ReactNode }) {
  return (
    <figure className="tune-qa">
      <h3 className="tune-q">{question}</h3>
      <p className="tune-a">{answer}</p>
      <figcaption className="tune-why">{children}</figcaption>
      <div className="tune-chart">{chart}</div>
    </figure>
  );
}

function Ticks({ ticks, min, max, format }: { ticks: number[]; min: number; max: number; format: (v: number) => string }) {
  return (
    <div className="tune-axis" aria-hidden="true">
      {ticks.map((t) => <span key={t} className={t <= min ? "start" : t >= max ? "end" : undefined} style={{ left: pct(t, min, max) }}>{format(t)}</span>)}
    </div>
  );
}

function Grid({ ticks, min, max }: { ticks: number[]; min: number; max: number }) {
  return <>{ticks.map((t) => <span key={t} className="tune-grid" style={{ left: pct(t, min, max) }} aria-hidden="true" />)}</>;
}

/** Options as dots on one scale: for results close together, where bars from zero would all look the same. */
export function DotPlot({ rows, min, max, ticks, format, label, unit }: {
  rows: Row[]; min: number; max: number; ticks: number[]; format: (v: number) => string; label: string; unit: string;
}) {
  return (
    <>
      <div className="tune-rows" role="list" aria-label={label}>
        {rows.map((r) => (
          <div key={r.label} className={r.chosen ? "tune-row chosen" : "tune-row"} role="listitem" tabIndex={0}
            aria-label={`${r.label}: ${format(r.value)}${r.chosen ? ", chosen" : ""}`}>
            <span className="tune-label">{r.label}{r.chosen && <span className="tune-chosen">Chosen</span>}</span>
            <span className="tune-track">
              <Grid ticks={ticks} min={min} max={max} />
              <span className="tune-dot" style={{ left: pct(r.value, min, max) }} />
              <span className={side(r.value, min, max)} style={{ left: pct(r.value, min, max) }}>{format(r.value)} {unit}{r.detail ? `. ${r.detail}` : ""}</span>
            </span>
            <span className="tune-value">{format(r.value)}</span>
          </div>
        ))}
        <div className="tune-row tune-axis-row" aria-hidden="true"><span /><Ticks ticks={ticks} min={min} max={max} format={format} /><span /></div>
      </div>
    </>
  );
}

/** Horizontal bars from a zero line (`min` below 0 for signed values, with optional ± spread whiskers). */
export function Bars({ rows, min = 0, max, ticks, format, label, unit }: {
  rows: Row[]; min?: number; max: number; ticks: number[]; format: (v: number) => string; label: string; unit: string;
}) {
  const zero = pct(0, min, max);
  return (
    <>
      <div className="tune-rows" role="list" aria-label={label}>
        {rows.map((r) => {
          const from = Math.min(0, r.value), to = Math.max(0, r.value);
          const bar: CSSProperties = { left: pct(from, min, max), width: `calc(${pct(to, min, max)} - ${pct(from, min, max)})` };
          return (
            <div key={r.label} className={r.chosen ? "tune-row chosen" : "tune-row"} role="listitem" tabIndex={0}
              aria-label={`${r.label}: ${format(r.value)}${r.spread ? ` give or take ${format(r.spread)}` : ""}${r.chosen ? ", chosen" : ""}`}>
              <span className="tune-label">{r.label}{r.chosen && <span className="tune-chosen">Chosen</span>}</span>
              <span className="tune-track">
                <Grid ticks={ticks} min={min} max={max} />
                {min < 0 && <span className="tune-zero" style={{ left: zero }} />}
                <span className={r.value < 0 ? "tune-bar neg" : "tune-bar"} style={bar} />
                {r.spread !== undefined && (
                  <span className="tune-spread" style={{ left: pct(r.value - r.spread, min, max), width: `calc(${pct(r.value + r.spread, min, max)} - ${pct(r.value - r.spread, min, max)})` }} />
                )}
                <span className={side(r.value, min, max)} style={{ left: pct(r.value, min, max) }}>
                  {format(r.value)}{r.spread ? ` ± ${format(r.spread)}` : ""} {unit}{r.detail ? `. ${r.detail}` : ""}
                </span>
              </span>
              <span className="tune-value">{format(r.value)}</span>
            </div>
          );
        })}
        <div className="tune-row tune-axis-row" aria-hidden="true"><span /><Ticks ticks={ticks} min={min} max={max} format={format} /><span /></div>
      </div>
    </>
  );
}

export interface Series { name: string; values: number[]; tone: "pick" | "alt" }

/** Two series over an ordered setting, with the chosen point ringed. Hover or focus a column for both values. */
export function LineChart({ xs, xLabel, series, min, max, ticks, format, chosen, label, endLabels = true }: {
  xs: string[]; xLabel: string; series: Series[]; min: number; max: number; ticks: number[];
  format: (v: number) => string; chosen: { series: number; x: number }; label: string;
  /** Name each line at its end. Off where the lines end too close together to label (the legend still names them). */
  endLabels?: boolean;
}) {
  const named = series.length > 1;   // one line is named by the chart's question; more get a legend and end labels
  const [at, setAt] = useState<number | null>(null);
  const x = (i: number) => (xs.length === 1 ? 40 : 6 + (i / (xs.length - 1)) * 72);   // the right fifth holds the line labels
  const y = (v: number) => 100 - ((v - min) / (max - min)) * 100;
  return (
    <>
      {named && (
        <ul className="tune-legend" aria-label="Lines">
          {series.map((s) => <li key={s.name}><span className={`tune-key ${s.tone}`} />{s.name}</li>)}
        </ul>
      )}
      <div className="tune-line" role="group" aria-label={label}>
        <div className="tune-yaxis" aria-hidden="true">
          {ticks.map((t) => <span key={t} style={{ top: `${y(t)}%` }}>{format(t)}</span>)}
        </div>
        <div className="tune-plot" onMouseLeave={() => setAt(null)}>
          {ticks.map((t) => <span key={t} className="tune-hgrid" style={{ top: `${y(t)}%` }} aria-hidden="true" />)}
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            {series.map((s) => (
              <polyline key={s.name} className={`tune-stroke ${s.tone}`} fill="none" vectorEffect="non-scaling-stroke"
                points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
            ))}
          </svg>
          {at !== null && <span className="tune-cross" style={{ left: `${x(at)}%` }} aria-hidden="true" />}
          {series.map((s, si) => s.values.map((v, i) => (
            <span key={`${si}-${i}`} aria-hidden="true"
              className={`tune-point ${s.tone}${chosen.series === si && chosen.x === i ? " chosen" : ""}`}
              style={{ left: `${x(i)}%`, top: `${y(v)}%` }} />
          )))}
          {named && endLabels && series.map((s) => (
            <span key={s.name} className="tune-end" aria-hidden="true" style={{ left: `${x(xs.length - 1)}%`, top: `${y(s.values[s.values.length - 1])}%` }}>
              {s.name}
            </span>
          ))}
          {xs.map((xv, i) => (
            <button key={xv} type="button" className="tune-hit" style={{ left: `${x(i)}%` }}
              aria-label={`${xLabel} ${xv}: ${series.map((s) => `${s.name} ${format(s.values[i])}`).join(", ")}`}
              onMouseEnter={() => setAt(i)} onFocus={() => setAt(i)} onBlur={() => setAt(null)} />
          ))}
          {at !== null && (
            <span className={`tune-tip shown${at === 0 ? " start" : at === xs.length - 1 ? " end" : ""}`} style={{ left: `${x(at)}%`, top: 0 }}>
              <strong>{xLabel} {xs[at]}</strong>
              {series.map((s) => <span key={s.name} className="tune-tip-row"><span className={`tune-key ${s.tone}`} />{s.name}: {format(s.values[at])}</span>)}
            </span>
          )}
        </div>
        <div className="tune-xaxis" aria-hidden="true">
          {xs.map((xv, i) => <span key={xv} style={{ left: `${x(i)}%` }}>{xv}</span>)}
        </div>
        <p className="tune-xlabel" aria-hidden="true">{xLabel}</p>
      </div>
    </>
  );
}

/** Two bars per row from zero: the alternative (--chart-rest) above the chosen setting (--chart-pick). */
export function PairedBars({ rows, from, to, max, ticks, format, label }: {
  rows: { label: string; before: number; after: number }[]; from: string; to: string;
  max: number; ticks: number[]; format: (v: number) => string; label: string;
}) {
  return (
    <>
      <ul className="tune-legend" aria-label="Bars">
        <li><span className="tune-key box" />{from}</li>
        <li><span className="tune-key box pick" />{to}</li>
      </ul>
      <div className="tune-rows" role="list" aria-label={label}>
        {rows.map((r) => (
          <div key={r.label} className="tune-row" role="listitem" tabIndex={0} aria-label={`${r.label}: ${format(r.before)} with ${from}, ${format(r.after)} with ${to}`}>
            <span className="tune-label">{r.label}</span>
            <span className="tune-track tune-pair-track">
              <Grid ticks={ticks} min={0} max={max} />
              <span className="tune-bar first" style={{ left: 0, width: pct(r.before, 0, max) }} />
              <span className="tune-bar second" style={{ left: 0, width: pct(r.after, 0, max) }} />
              <span className={side(r.after, 0, max)} style={{ left: pct(r.after, 0, max) }}>{from}: {format(r.before)}. {to}: {format(r.after)}</span>
            </span>
            <span className="tune-value">{format(r.after)}</span>
          </div>
        ))}
        <div className="tune-row tune-axis-row" aria-hidden="true"><span /><Ticks ticks={ticks} min={0} max={max} format={format} /><span /></div>
      </div>
    </>
  );
}
