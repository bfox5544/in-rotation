import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ProfileFields, ProfileSettings, errorText } from "../components/ProfileSettings";
import { useLibrary } from "../state/library";
import { ThemePicker } from "../components/ThemePicker";

type Mode = "register" | "login";

/** Sign up or sign in. An account is a profile (ADR 0018): signed in, this page is your profile's Settings tab. */
export default function Account() {
  const { email, profile, rated, later, lists, reload, whenSynced } = useLibrary();
  const [mode, setMode] = useState<Mode>("register");
  const [form, setForm] = useState({ email: "", password: "" });
  const [fields, setFields] = useState({ username: "", displayName: "", public: false });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const nav = useNavigate();
  const saved = rated.length + later.length + lists.reduce((n, l) => n + l.albums.length, 0);

  if (email && profile) return <Navigate to={`/u/${profile.username}?tab=settings`} replace />;
  if (email) return <ProfileSettings />;     // an account made before profiles: choose a username first

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await whenSynced();
      if (mode === "register") {
        const me = await api.register({ ...form, ...fields });
        await reload();
        nav(me.profile ? `/u/${me.profile.username}` : "/library");
      } else {
        await api.login(form.email, form.password);
        await reload();
        nav("/library");
      }
    } catch (err) {
      setProblem(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const register = mode === "register";
  return (
    <section className="section account">
      <h1 className="page-title">{register ? "Create Your Profile" : "Sign In"}</h1>
      <div className="filters" role="tablist" aria-label="Account">
        {(["register", "login"] as Mode[]).map((m) => (
          <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? "filter active" : "filter"}
            onClick={() => { setMode(m); setProblem(null); }}>
            {m === "register" ? "Create Account" : "Sign In"}
          </button>
        ))}
      </div>
      <p className="muted">
        {register
          ? `Your account is your profile. It keeps ${saved > 0 ? `the ${saved} albums you've saved` : "what you save"}, lets you sign in from other browsers, and gives you a page with your ratings and Insights. It stays private unless you make it public.`
          : saved > 0
            ? `The ${saved} albums saved in this browser will be added to your account.`
            : "Sign in to get your library on this browser."}
      </p>
      <form className="account-form" onSubmit={submit}>
        {register && <ProfileFields form={fields} onChange={setFields} />}
        <label>
          Email
          <input type="email" autoComplete="email" required value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })} />
          {register && <span className="hint">For signing in only. Never shown on your profile.</span>}
        </label>
        <label>
          Password
          <input type="password" autoComplete={register ? "new-password" : "current-password"} required
            minLength={register ? 8 : undefined} value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
          {register && <span className="hint">At least 8 characters.</span>}
        </label>
        {problem && <p className="notice" role="alert">{problem}</p>}
        <button className="btn" type="submit" disabled={busy}>{register ? "Create Account" : "Sign In"}</button>
      </form>
      <ThemePicker />
    </section>
  );
}
