/**
 * Who may read a project, and the two buttons that change it.
 *
 * This replaces opening a shell, which is what granting a project used to take. The rule
 * itself has not moved — it is still a row in `app.membership`, and `services/permission`
 * is still the only thing that reads it.
 *
 * There is no administrator role: anyone who may read a project may invite into it. One
 * would need a table, a way to become one, and a first one to bootstrap, and the answer
 * to all three would be the shell this screen exists to replace.
 */

import { useEffect, useState } from "react";
import type { Member } from "../api";
import { addMember, fetchMembers, fetchProjects, removeMember } from "../api";
import { Spinner } from "./icons";

export function AccessPanel() {
  const [projects, setProjects] = useState<string[]>([]);
  const [project, setProject] = useState<string | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    void fetchProjects()
      .then((found) => {
        setProjects(found);
        setProject((current) => current ?? found[0] ?? null);
      })
      .catch((error: unknown) => setFailure(String(error)));
  }, []);

  useEffect(() => {
    if (!project) return;
    void fetchMembers(project)
      .then(setMembers)
      .catch((error: unknown) => setFailure(String(error)));
  }, [project]);

  const refresh = async (): Promise<void> => {
    if (project) setMembers(await fetchMembers(project));
  };

  const run = async (work: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await work();
      await refresh();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  if (!projects.length) {
    return (
      <p className="muted">
        You cannot read any project yet, so there is nothing to share. Someone who can read
        one can add you to it here.
      </p>
    );
  }

  return (
    <>
      <section>
        <h3 className="label">Project</h3>
        <div className="choice-list">
          {projects.map((key) => (
            <button key={key} aria-pressed={key === project} onClick={() => setProject(key)}>
              <b>{key}</b>
            </button>
          ))}
        </div>
      </section>

      <section>
        <h3 className="label">Who may read it</h3>
        <ul className="members">
          {members.map((member) => (
            <li key={member.id}>
              <span>{member.email}</span>
              <button
                className="quiet"
                disabled={busy}
                onClick={() => void run(() => removeMember(project!, member.email))}
              >
                Remove
              </button>
            </li>
          ))}
          {!members.length && <li className="muted">Nobody yet.</li>}
        </ul>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await addMember(project!, email);
              setEmail("");
            });
          }}
        >
          <label>
            <span className="label">Add by email</span>
            <input
              type="email"
              required
              placeholder="someone@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <span className="hint">They need an account already — this grants, it does not invite.</span>
          </label>

          {failure && <p className="failure">{failure}</p>}

          <button className="primary" type="submit" disabled={busy}>
            {busy && <Spinner className="spin" size={14} />}
            Grant
          </button>
        </form>
      </section>
    </>
  );
}
