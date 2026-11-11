import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { useLibrary } from "../state/library";
import { useToast } from "../state/toast";
import { Avatar } from "./Avatar";
import { ThemePicker } from "./ThemePicker";

export const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "Something went wrong. Try again in a moment.");

/** The fields an account's profile has (ADR 0018), shared by sign-up and settings. */
export function ProfileFields({ form, onChange }: {
  form: { username: string; displayName: string; public: boolean };
  onChange: (next: { username: string; displayName: string; public: boolean }) => void;
}) {
  return (
    <>
      <label>
        Name
        <input value={form.displayName} maxLength={40} required autoComplete="nickname"
          onChange={(e) => onChange({ ...form, displayName: e.target.value })} />
      </label>
      <label>
        Username
        <input value={form.username} maxLength={21} required pattern="@?[A-Za-z0-9_]{3,20}" autoCapitalize="none" spellCheck={false}
          autoComplete="username" onChange={(e) => onChange({ ...form, username: e.target.value })} />
        <span className="hint">3 to 20 letters, numbers or underscores. Your profile's address: /u/{form.username.trim().toLowerCase().replace(/^@/, "") || "name"}</span>
      </label>
      <label className="check">
        <input type="checkbox" checked={form.public} onChange={(e) => onChange({ ...form, public: e.target.checked })} />
        <span>Public Profile<span className="hint">Anyone with the link can see your name, picture, ratings and Insights. When this is off, only you can.</span></span>
      </label>
    </>
  );
}

/** Your account and profile settings: picture, name, username, visibility, sign out. */
export function ProfileSettings() {
  const { email, profile, setProfile, reload, whenSynced } = useLibrary();
  const [form, setForm] = useState({
    username: profile?.username ?? "", displayName: profile?.displayName ?? "", public: profile?.public ?? false,
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const toast = useToast();
  const [deleting, setDeleting] = useState(false);
  const [password, setPassword] = useState("");
  const [deleteProblem, setDeleteProblem] = useState<string | null>(null);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setProblem(null);
    setSaved(false);
    try {
      await work();
    } catch (err) {
      setProblem(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const next = await api.saveProfile(form);
      setProfile(next);
      setForm({ username: next.username, displayName: next.displayName, public: next.public });
      setSaved(true);
      if (next.username !== profile?.username) nav(`/u/${next.username}?tab=settings`, { replace: true });
    });
  };
  const upload = (f: File | undefined) => {
    if (file.current) file.current.value = "";
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) {
      setProblem("That image is over 8 MB");
      return;
    }
    run(async () => setProfile(await api.uploadPicture(f)));
  };
  const signOut = () =>
    run(async () => {
      await whenSynced();
      await api.logout();
      await reload();
      nav("/");
    });

  const deleteAccount = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setDeleteProblem(null);
    try {
      await whenSynced();
      await api.deleteAccount(password);
      await reload();
      toast({ message: <>Your account and everything in it were deleted.</> });
      nav("/");
    } catch (err) {
      setDeleteProblem(errorText(err));
      setBusy(false);
    }
  };

  return (
    <section className="section account profile-settings" aria-labelledby="settings-heading">
      <h2 id="settings-heading">{profile ? "Profile Settings" : "Finish Your Profile"}</h2>
      {!profile && <p className="muted">Your account was made before profiles existed. Choose a name and a username to finish it.</p>}
      {profile && (
        <div className="avatar-row">
          <Avatar url={profile.avatarUrl} name={profile.displayName} size={88} />
          <div className="avatar-actions">
            <input ref={file} type="file" accept="image/jpeg,image/png,image/webp,image/gif" className="visually-hidden"
              id="avatar-file" onChange={(e) => upload(e.target.files?.[0])} disabled={busy} />
            <label htmlFor="avatar-file" className="btn btn-quiet btn-small" aria-disabled={busy}>
              {profile.avatarUrl ? "Change Picture" : "Add Picture"}
            </label>
            {profile.avatarUrl && (
              <button type="button" className="btn btn-quiet btn-small" disabled={busy}
                onClick={() => run(async () => setProfile(await api.deletePicture()))}>
                Remove Picture
              </button>
            )}
            <span className="hint">JPEG, PNG, WebP or GIF, up to 8 MB. Cropped to a square.</span>
          </div>
        </div>
      )}
      <form className="account-form" onSubmit={submit}>
        <ProfileFields form={form} onChange={setForm} />
        {problem && <p className="notice" role="alert">{problem}</p>}
        {saved && <p className="muted" role="status">Saved.</p>}
        <button className="btn" type="submit" disabled={busy}>{profile ? "Save Changes" : "Finish Profile"}</button>
      </form>
      <ThemePicker />
      <div className="account-signout">
        <h3>Account</h3>
        <p className="muted">Signed in as <strong>{email}</strong>. Your email is never shown on your profile. Listen Later and your lists stay private.</p>
        <p className="muted">Signing out leaves this browser with a new, empty library. Everything stays in your account.</p>
        <button type="button" className="btn btn-quiet" onClick={signOut} disabled={busy}>Sign Out</button>
      </div>
      <div className="account-delete">
        <h3>Delete Account</h3>
        <p className="muted">
          This deletes your account, profile, picture, ratings, lists and Ask chats for good. It can't be undone, and
          every browser signed in to it starts again with an empty library.
        </p>
        {!deleting ? (
          <button type="button" className="btn btn-quiet btn-danger" onClick={() => setDeleting(true)} disabled={busy}>Delete Account</button>
        ) : (
          <form className="account-form" onSubmit={deleteAccount}>
            <label>
              Enter Your Password to Confirm
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                autoComplete="current-password" autoFocus />
            </label>
            {deleteProblem && <p className="notice" role="alert">{deleteProblem}</p>}
            <div className="account-delete-actions">
              <button type="submit" className="btn btn-danger" disabled={busy || !password}>Delete My Account</button>
              <button type="button" className="btn btn-quiet" disabled={busy}
                onClick={() => { setDeleting(false); setPassword(""); setDeleteProblem(null); }}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
