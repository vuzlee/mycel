/**
 * The user's documents, live. One SSE stream for the whole app: the server sends the full
 * list again whenever a document changes state, so the page never polls and never merges.
 */

import { useEffect, useState } from "react";
import type { DocumentRow, DocumentStatus } from "../api";

export interface Documents {
  documents: DocumentRow[];
  /** A document is still processing: the knowledge base cannot be asked. */
  busy: boolean;
  ready: boolean;
}

export function useDocuments(): Documents {
  const [state, setState] = useState<Documents>({ documents: [], busy: false, ready: false });

  useEffect(() => {
    const source = new EventSource("/documents/status");
    source.onmessage = (event: MessageEvent<string>) => {
      const status = JSON.parse(event.data) as DocumentStatus;
      setState({ documents: status.documents, busy: status.busy, ready: true });
    };
    return () => source.close();
  }, []);

  return state;
}
