import { useEffect, useState } from "react";
import {
  connectGoogle,
  connectJira,
  disconnectGoogle,
  disconnectJira,
  fetchGoogle,
  fetchJira,
} from "../../api";
import { Board, Calendar, Spinner } from "../icons";

function outcome(provider: "google" | "jira"): "connected" | "failed" | null {
  const query = new URLSearchParams(window.location.search);
  if (query.has(provider)) return "connected";
  if (query.has(`${provider}_error`)) return "failed";
  return null;
}

/** One account a person connects. Adding a provider is one entry in `CONNECTIONS` — the
 *  status call, the consent redirect and the disconnect are all it needs from `api.ts`. */
interface Provider {
  id: "google" | "jira";
  title: string;
  icon: React.ReactNode;
  /** One line, shown before connecting: what connecting opens. */
  offers: string;
  status: () => Promise<{
    configured: boolean;
    who: string | null;
    since: string | null;
    note?: string;
  }>;
  connect: () => void;
  disconnect: () => Promise<void>;
}

export const CONNECTIONS: Provider[] = [
  {
    id: "google",
    title: "Google",
    icon: <Calendar size={16} />,
    offers: "Your own calendar and mail. Mail is read-only; nothing is deleted.",
    status: async () => {
      const s = await fetchGoogle();
      return { configured: s.configured, who: s.email, since: s.connected_at };
    },
    connect: connectGoogle,
    disconnect: disconnectGoogle,
  },
  {
    id: "jira",
    title: "Jira",
    icon: <Board size={16} />,
    offers: "The projects Jira lets you browse. Writes only after you agree.",
    status: async () => {
      const s = await fetchJira();
      const note = s.display_name
        ? s.projects.length
          ? `Reads ${s.projects.join(", ")}`
          : "Jira lets this account browse no project"
        : undefined;
      return {
        configured: s.configured,
        who: s.display_name,
        since: s.connected_at,
        note,
      };
    },
    connect: connectJira,
    disconnect: disconnectJira,
  },
];

type Status = Awaited<ReturnType<Provider["status"]>>;

/** One provider's card: not set up here, connected, or not yet. */
export function Connection({ provider }: { provider: Provider }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [came] = useState(() => outcome(provider.id));

  useEffect(() => {
    void provider
      .status()
      .then(setStatus)
      .catch(() => setStatus(null));
    if (came) window.history.replaceState({}, "", window.location.pathname);
  }, [came, provider]);

  const drop = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await provider.disconnect();
      setStatus(await provider.status());
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="connection">
      <header className="connection-head">
        <span className="connection-icon" aria-hidden>
          {provider.icon}
        </span>
        <h4>{provider.title}</h4>
        {status?.who && <span className="pill on">Connected</span>}
      </header>
      {status === null && <p className="muted">Checking…</p>}
      {status && !status.configured && (
        <p className="muted">Not set up on this deployment — see docs/setup.md.</p>
      )}
      {status?.configured && status.who && (
        <>
          <div className="connection-who">
            <b>{status.who}</b>
            <span className="muted">
              since {status.since ? new Date(status.since).toLocaleDateString() : "—"}
            </span>
          </div>
          {status.note && <p className="muted">{status.note}</p>}
          {failure && <p className="failure">{failure}</p>}
          <button className="outline" onClick={() => void drop()} disabled={busy}>
            {busy && <Spinner className="spin" size={14} />}
            Disconnect
          </button>
        </>
      )}
      {status?.configured && !status.who && (
        <>
          <p className="muted">{provider.offers}</p>
          {came === "failed" && (
            <p className="failure">That did not finish. Nothing was connected.</p>
          )}
          <button className="primary" onClick={provider.connect}>
            Connect {provider.title}
          </button>
        </>
      )}
    </section>
  );
}
