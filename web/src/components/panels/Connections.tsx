import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { connectPlugin, disconnectPlugin, fetchPlugins, type PluginStatus } from "../../api";
import { Board, Calendar, Chip, Spinner } from "../icons";

const KEY = ["plugins"];

/** Icons by plugin key; an unknown plugin gets the generic one. */
const ICONS: Record<string, React.ReactNode> = {
  google: <Calendar size={16} />,
  jira: <Board size={16} />,
};

function outcome(key: string): "connected" | "failed" | null {
  const query = new URLSearchParams(window.location.search);
  if (query.has(key)) return "connected";
  if (query.has(`${key}_error`)) return "failed";
  return null;
}

/** Every plugin the server ships, one card each. */
export function Connections() {
  const { data: plugins = null } = useQuery({ queryKey: KEY, queryFn: fetchPlugins });
  if (plugins === null) return <p className="muted">Checking…</p>;
  return (
    <>
      {plugins.map((p) => (
        <Connection key={p.key} plugin={p} />
      ))}
    </>
  );
}

/** One plugin's card: not set up here, connected, or not yet. */
function Connection({ plugin }: { plugin: PluginStatus }) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [came] = useState(() => outcome(plugin.key));

  useEffect(() => {
    if (came) window.history.replaceState({}, "", window.location.pathname);
  }, [came]);

  const drop = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      await disconnectPlugin(plugin.key);
      await client.invalidateQueries({ queryKey: KEY });
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
          {ICONS[plugin.key] ?? <Chip size={16} />}
        </span>
        <h4>{plugin.name}</h4>
        {plugin.who && <span className="pill on">Connected</span>}
      </header>
      {!plugin.configured && (
        <p className="muted">Not set up on this deployment — see docs/operate/setup.md.</p>
      )}
      {plugin.configured && plugin.who && (
        <>
          <div className="connection-who">
            <b>{plugin.who}</b>
            <span className="muted">
              since {plugin.since ? new Date(plugin.since).toLocaleDateString() : "—"}
            </span>
          </div>
          {plugin.note && <p className="muted">{plugin.note}</p>}
          {failure && <p className="failure">{failure}</p>}
          <button className="outline" onClick={() => void drop()} disabled={busy}>
            {busy && <Spinner className="spin" size={14} />}
            Disconnect
          </button>
        </>
      )}
      {plugin.configured && !plugin.who && (
        <>
          <p className="muted">{plugin.offers}</p>
          {came === "failed" && (
            <p className="failure">That did not finish. Nothing was connected.</p>
          )}
          <button className="primary" onClick={() => connectPlugin(plugin.key)}>
            Connect {plugin.name}
          </button>
        </>
      )}
    </section>
  );
}
