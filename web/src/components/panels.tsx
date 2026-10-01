/**
 * What the account menu opens: the account, the settings, and how to use this.
 *
 * Panels rather than pages — each is a few blocks someone reads and dismisses, and all
 * three live here because they are the same size and the same shape. A file each would
 * be three files of twenty lines.
 */

import { useEffect, useState } from "react";
import type { GoogleStatus, Thread } from "../api";
import {
  changePassword,
  connectGoogle,
  disconnectGoogle,
  fetchGoogle,
} from "../api";
import { useAuth } from "../auth";
import { Calendar, Moon, Screen, Spinner, Sun } from "./icons";
import type { Theme } from "../theme";
import { useTheme } from "../theme";

const REPO = "https://github.com/vuzlee/mycel";
const CONTACT = "levu040102@gmail.com";

/** The account, as the server knows it. The address cannot be changed — it is the
 *  identity — and the password can, which is why one of the two has a form. */
export function ProfilePanel({ threads }: { threads: Thread[] }) {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <div className="identity">
        <span className="avatar big" aria-hidden>
          {user.email.charAt(0).toUpperCase()}
        </span>
        <div>
          <b>{user.email}</b>
          <span className="muted">Account #{user.id}</span>
        </div>
      </div>

      <dl className="facts">
        <div>
          <dt>Runs kept</dt>
          <dd>{threads.length}</dd>
        </div>
        <div>
          <dt>Sign-in</dt>
          <dd>Password</dd>
        </div>
      </dl>

      <p className="muted">
        Your runs are kept under this account, so signing in on another machine brings them
        with you. The address is the identity here and cannot be changed.
      </p>

      <PasswordForm />
    </>
  );
}

/** Changing the password needs the current one even though a valid cookie is already in
 *  hand: a borrowed laptop is exactly the case that protects against. Every other session
 *  ends, and this one does not — you stay in the tab you are typing in. */
function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    setDone(false);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setDone(true);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h3 className="label">Change password</h3>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label>
          <span className="label">Current password</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </label>

        <label>
          <span className="label">New password</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
          <span className="hint">At least 8 characters.</span>
        </label>

        {failure && <p className="failure">{failure}</p>}
        {done && <p className="notice">Changed. Every other browser has been signed out.</p>}

        <button className="primary" type="submit" disabled={busy}>
          {busy && <Spinner className="spin" size={14} />}
          Change it
        </button>
      </form>
    </section>
  );
}

const THEMES: { value: Theme; label: string; icon: JSX.Element }[] = [
  { value: "system", label: "System", icon: <Screen size={17} /> },
  { value: "light", label: "Light", icon: <Sun size={17} /> },
  { value: "dark", label: "Dark", icon: <Moon size={17} /> },
];

/** Two settings: how it looks here, and which calendar it may read.
 *
 *  They sit together because both are answers to "how does this behave for me", and neither
 *  is big enough for a screen of its own. Appearance is per-browser; the Google connection
 *  is per-account, which the copy under each one says. */
export function SettingsPanel() {
  const [theme, choose] = useTheme();

  return (
    <>
      <section>
        <h3 className="label">Appearance</h3>
        <div className="theme-picker">
          {THEMES.map((option) => (
            <button
              key={option.value}
              aria-pressed={theme === option.value}
              onClick={() => choose(option.value)}
            >
              {option.icon}
              {option.label}
            </button>
          ))}
        </div>
        <p className="muted">Kept in this browser — another machine keeps its own.</p>
      </section>

      <GoogleSection />
    </>
  );
}

/** The outcome of a consent round, which arrives in the query string rather than in a
 *  response: the browser left for Google's own screen and came back by redirect, so there
 *  was no fetch to answer. Read once and cleared from the address bar, so reloading the
 *  page does not re-announce a connection made ten minutes ago. */
function outcome(): "connected" | "failed" | null {
  const query = new URLSearchParams(window.location.search);
  if (query.has("google")) return "connected";
  if (query.has("google_error")) return "failed";
  return null;
}

/** Connecting a Google account, so a question about the calendar has one to read.
 *
 *  Three states, and the first is about the deployment rather than the person: a machine
 *  with no OAuth client cannot connect anything, and saying so is better than a button that
 *  leads to an error. Then connected, and not. */
function GoogleSection() {
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [came] = useState(outcome);

  useEffect(() => {
    void fetchGoogle().then(setStatus).catch(() => setStatus(null));
    if (came) window.history.replaceState({}, "", window.location.pathname);
  }, [came]);

  const drop = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await disconnectGoogle();
      setStatus(await fetchGoogle());
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h3 className="label">Google Calendar</h3>

      {status === null && <p className="muted">Checking…</p>}

      {status && !status.configured && (
        <p className="muted">
          This deployment has no Google client configured, so no calendar can be connected.
          Whoever runs it sets <code>GOOGLE_CLIENT_ID</code>,{" "}
          <code>GOOGLE_CLIENT_SECRET</code> and <code>GOOGLE_TOKEN_KEY</code>.
        </p>
      )}

      {status?.configured && status.email && (
        <>
          <div className="identity">
            <span className="avatar big" aria-hidden>
              <Calendar size={17} />
            </span>
            <div>
              <b>{status.email}</b>
              <span className="muted">
                Connected{" "}
                {status.connected_at
                  ? new Date(status.connected_at).toLocaleDateString()
                  : ""}
              </span>
            </div>
          </div>
          <p className="muted">
            Questions about your time read this calendar, and a booking you agree to is
            written to it. Nothing else is read, and nothing is ever deleted.
          </p>
          {failure && <p className="failure">{failure}</p>}
          <button onClick={() => void drop()} disabled={busy}>
            {busy && <Spinner className="spin" size={14} />}
            Disconnect
          </button>
        </>
      )}

      {status?.configured && !status.email && (
        <>
          <p className="muted">
            Connect one and you can ask what is on this afternoon, or say "3pm tomorrow,
            team, half an hour" and agree to what it reads back. Nothing is written until you
            do — and nothing here can delete an event.
          </p>
          {came === "failed" && (
            <p className="failure">That did not finish. Nothing was connected.</p>
          )}
          <button className="primary" onClick={connectGoogle}>
            <Calendar size={14} />
            Connect Google Calendar
          </button>
        </>
      )}
    </section>
  );
}

const STEPS = [
  {
    title: "Keep your tracker as you already do",
    body: "Mycel reads your Jira project — issues, epics, estimates, worklogs and due dates. Nobody fills in a second form, and nothing here writes back to it.",
  },
  {
    title: "Read the week",
    body: "Ask for a project's progress over any window and it writes it up: what shipped, what is still moving, and which ticket is late.",
  },
  {
    title: "Read the numbers",
    body: "Ask for a count instead and it writes its own SQL against the work data: totals by status, estimated against spent per person, effort logged per day. Every figure comes back with the query that produced it.",
  },
  {
    title: "Ask anything else",
    body: "The same box reads your mailbox and searches the web, so a question does not have to be about your tracker to have an answer.",
  },
];

export function HelpPanel() {
  return (
    <>
      <ol className="steps">
        {STEPS.map((step) => (
          <li key={step.title}>
            <b>{step.title}</b>
            <span className="muted">{step.body}</span>
          </li>
        ))}
      </ol>

      <section>
        <h3 className="label">If something is wrong</h3>
        <p className="muted">
          Open an issue at{" "}
          <a href={`${REPO}/issues`} target="_blank" rel="noreferrer">
            the repository
          </a>
          , or write to <a href={`mailto:${CONTACT}`}>{CONTACT}</a>. Replies are from one
          person, so give it a day.
        </p>
      </section>
    </>
  );
}
