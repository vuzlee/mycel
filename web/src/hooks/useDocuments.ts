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

export function useDocuments(): Documents {
  const { forget } = useAuth();
  const [state, setState] = useState<Documents>({
    documents: [],
    busy: false,
    loading: true,
    error: null,
  });

  useEffect(() => {
    const source = new EventSource("/documents/status");
    source.onmessage = (event: MessageEvent<string>) => {
      const status = JSON.parse(event.data) as DocumentStatus;
      setState({ documents: status.documents, busy: status.busy, loading: false, error: null });
    };
    source.onerror = () => {
      setState((s) => ({ ...s, loading: false, error: LOST }));
      // The browser retries a dropped stream itself; a refused one (401, 5xx) is closed for good.
      if (source.readyState !== EventSource.CLOSED) return;
      void me().then((user) => {
        if (user === null) forget();
        else setState((s) => ({ ...s, error: "Could not load your documents." }));
      });
    };
    return () => source.close();
  }, [forget]);

  return state;
}
