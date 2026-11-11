import { useState, type FormEvent } from "react";
import { api } from "../api";
import { InfoPage, InfoSection } from "../components/InfoPage";
import { errorText } from "../components/ProfileSettings";

const TOPICS = [
  { key: "feedback", label: "General Feedback" },
  { key: "recommendations", label: "Recommendations" },
  { key: "data", label: "Album Data" },
  { key: "bug", label: "Something Isn't Working" },
  { key: "other", label: "Something Else" },
];
const MAX = 2000;
// Optional public address, set at build time in web/.env (VITE_CONTACT_EMAIL). Left out when empty.
const CONTACT_EMAIL = import.meta.env.VITE_CONTACT_EMAIL?.trim();

export default function Contact() {
  const [form, setForm] = useState({ topic: "feedback", message: "", replyTo: "" });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.sendFeedback({ topic: form.topic, message: form.message, replyTo: form.replyTo || null });
      setSent(true);
      setForm({ ...form, message: "" });
    } catch (err) {
      setProblem(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <InfoPage title="Contact" lead="Questions, ideas, a wrong cover or a recommendation that missed? Send a message. Every one is read.">
      {CONTACT_EMAIL && (
        <p className="muted">You can also email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.</p>
      )}
      <InfoSection title="Send Feedback">
        {sent ? (
          <div className="feedback-sent" role="status">
            <p>Thanks. Your message was sent.</p>
            <button type="button" className="btn btn-quiet btn-small" onClick={() => setSent(false)}>Send Another</button>
          </div>
        ) : (
          <form className="account-form feedback-form" onSubmit={submit}>
            <label>
              Topic
              <select value={form.topic} onChange={(e) => setForm({ ...form, topic: e.target.value })}>
                {TOPICS.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
            </label>
            <label>
              Message
              <textarea required rows={6} maxLength={MAX} value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })} />
              <span className="hint">{form.message.length.toLocaleString("en")} of {MAX.toLocaleString("en")} characters</span>
            </label>
            <label>
              Email for a Reply
              <input type="email" autoComplete="email" value={form.replyTo} onChange={(e) => setForm({ ...form, replyTo: e.target.value })} />
              <span className="hint">Optional. Only used to answer you, never shown or shared.</span>
            </label>
            {problem && <p className="notice" role="alert">{problem}</p>}
            <button className="btn" type="submit" disabled={busy || !form.message.trim()}>{busy ? "Sending..." : "Send Message"}</button>
          </form>
        )}
      </InfoSection>
      <InfoSection title="">
        <p>In Rotation was made by Brandon Fox.</p>
      </InfoSection>
    </InfoPage>
  );
}
