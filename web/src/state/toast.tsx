import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

/** One short message at the bottom of the screen, optionally with an action such as Undo. */
interface Toast { message: ReactNode; action?: { label: string; run: () => void }; ms?: number }

const Ctx = createContext<(toast: Toast | null) => void>(() => undefined);
const TOAST_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<(Toast & { id: number }) | null>(null);
  const show = useCallback((t: Toast | null) => setToast(t && { ...t, id: Date.now() }), []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), toast.ms ?? TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);
  return (
    <Ctx.Provider value={show}>
      {children}
      {toast && (
        <div className="toast" role="status" key={toast.id}>
          <span>{toast.message}</span>
          {toast.action && (
            <button type="button" className="btn" onClick={() => { toast.action!.run(); setToast(null); }}>{toast.action.label}</button>
          )}
        </div>
      )}
    </Ctx.Provider>
  );
}

/** show({ message, action }) replaces any toast on screen; show(null) hides it. */
export const useToast = () => useContext(Ctx);
