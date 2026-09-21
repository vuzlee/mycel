/**
 * What the account menu opens: the account, the one setting, and how to use this.
 *
 * Panels rather than pages — each is a few blocks someone reads and dismisses, and all
 * three live here because they are the same size and the same shape. A file each would
 * be three files of twenty lines.
 */

import type { Thread } from "../api";
import { useAuth } from "../auth";
import type { Theme } from "../theme";
import { useTheme } from "../theme";

const REPO = "https://github.com/vuzlee/mycel";
const CONTACT = "levu040102@gmail.com";

/** The account, as the server knows it. Read-only: `app.user` holds an id, an email and
 *  a password hash, and no route changes any of them — a form that cannot save is worse
 *  than a page that says what is true. */
export function ProfilePanel({ threads }: { threads: Thread[] }) {
  const { user } = useAuth();
  if (!user) return null;

  const reports = threads.filter((thread) => thread.kind === "report").length;

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
          <dt>Reports</dt>
          <dd>{reports}</dd>
        </div>
        <div>
          <dt>Sign-in</dt>
          <dd>Password</dd>
        </div>
      </dl>

      <p className="muted">
        Your runs are kept under this account, so signing in on another machine brings them
        with you. Changing the address or the password is not built yet.
      </p>
    </>
  );
}

const THEMES: { value: Theme; label: string; how: string }[] = [
  { value: "system", label: "Match my machine", how: "Follows the device's own setting." },
  { value: "light", label: "Light", how: "Always light, whatever the device says." },
  { value: "dark", label: "Dark", how: "Always dark, whatever the device says." },
];

/** One setting, because there is one. "System" is a real third option rather than the
 *  absence of a choice: a boolean cannot say "follow the machine". */
export function SettingsPanel() {
  const [theme, choose] = useTheme();

  return (
    <>
      <section>
        <h3 className="label">Appearance</h3>
        <div className="choice-list">
          {THEMES.map((option) => (
            <button
              key={option.value}
              aria-pressed={theme === option.value}
              onClick={() => choose(option.value)}
            >
              <b>{option.label}</b>
              <span className="muted">{option.how}</span>
            </button>
          ))}
        </div>
        <p className="muted">Kept in this browser — another machine keeps its own.</p>
      </section>
    </>
  );
}

const STEPS = [
  {
    title: "Keep your tracker as you already do",
    body: "Mycel reads your Jira project — issues, epics, estimates, worklogs and due dates. Nobody fills in a second form, and nothing here writes back to it.",
  },
  {
    title: "Read the week",
    body: "Progress report picks a project and a window and writes it up: what shipped, what is still moving, and which ticket is late.",
  },
  {
    title: "Read the numbers",
    body: "Dashboard is the same window counted instead of written: totals by status, estimated against spent per person, progress by epic, and effort logged per day.",
  },
  {
    title: "Ask anything else",
    body: "Ask is for questions outside your team's messages — something to look up, or figures you hand it in the question itself.",
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
