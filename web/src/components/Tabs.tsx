/** A row of tabs whose selection lives in the URL (?tab=...), so it can be linked and Back works.
 *  The first tab is the default and leaves the parameter out. Arrow keys move between tabs. */
import { useSearchParams } from "react-router-dom";

export interface TabDef { key: string; label: string }

export function useTab(tabs: TabDef[]): [string, (key: string) => void] {
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab");
  const tab = tabs.some((t) => t.key === asked) ? asked! : tabs[0].key;
  return [tab, (key) => setParams(key === tabs[0].key ? {} : { tab: key })];
}

export function Tabs({ tabs, tab, select, label }: { tabs: TabDef[]; tab: string; select: (key: string) => void; label: string }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.key} type="button" role="tab" id={`tab-${t.key}`} aria-selected={tab === t.key}
          aria-controls={`panel-${t.key}`} tabIndex={tab === t.key ? 0 : -1} className={tab === t.key ? "tab active" : "tab"}
          onClick={() => select(t.key)}
          onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            const step = e.key === "ArrowRight" ? 1 : tabs.length - 1;
            const next = tabs[(tabs.findIndex((x) => x.key === tab) + step) % tabs.length];
            select(next.key);
            document.getElementById(`tab-${next.key}`)?.focus();
          }}>
          {t.label}
        </button>
      ))}
    </div>
  );
}
