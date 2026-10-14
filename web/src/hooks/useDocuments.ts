/** The user's documents, live over one SSE stream that resends the full list on change. */

import { useEffect, useState } from "react";
import { me, type DocumentRow, type DocumentStatus } from "../api";
import { useAuth } from "../context/auth";

export interface Documents {
  documents: DocumentRow[];
  /** A document is still processing: the knowledge base cannot be asked. */
  busy: boolean;
  /** No list has arrived yet. */
  loading: boolean;
  error: string | null;
}

const LOST = "Lost the connection to your documents. Retrying…";
const FIRST_RETRY_MS = 1000;
const LAST_RETRY_MS = 30_000;

export function useDocuments(): Documents {
  const { forget } = useAuth();
  const [state, setState] = useState<Documents>({
    documents: [],
    busy: false,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let wait = FIRST_RETRY_MS;
    let live = true;

    // The browser retries a dropped stream itself; a refused one (401, 5xx during a deploy)
    // is closed for good, so it is reopened here, waiting longer each time.
    const retry = (): void => {
      if (!live) return;
      timer = setTimeout(open, wait);
      wait = Math.min(wait * 2, LAST_RETRY_MS);
    };

    const open = (): void => {
      const current = new EventSource("/documents/status");
      source = current;
      current.onmessage = (event: MessageEvent<string>) => {
        let status: DocumentStatus;
        try {
          status = JSON.parse(event.data) as DocumentStatus;
        } catch {
          return;
        }
        wait = FIRST_RETRY_MS;
        setState({ documents: status.documents, busy: status.busy, loading: false, error: null });
      };
      current.onerror = () => {
        setState((s) => ({ ...s, loading: false, error: LOST }));
        if (current.readyState !== EventSource.CLOSED) return;
        me().then((user) => (user === null ? forget() : retry()), retry);
      };
    };

    open();
    return () => {
      live = false;
      clearTimeout(timer);
      source?.close();
    };
  }, [forget]);

  return state;
}
