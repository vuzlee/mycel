/** The user's documents, live over one SSE stream that resends the full list on change. */

import { useEffect, useState } from "react";
import type { DocumentRow, DocumentStatus } from "../api";

export interface Documents {
  documents: DocumentRow[];
  /** A document is still processing: the knowledge base cannot be asked. */
  busy: boolean;
}

export function useDocuments(): Documents {
  const [state, setState] = useState<Documents>({ documents: [], busy: false });

  useEffect(() => {
    const source = new EventSource("/documents/status");
    source.onmessage = (event: MessageEvent<string>) => {
      const status = JSON.parse(event.data) as DocumentStatus;
      setState({ documents: status.documents, busy: status.busy });
    };
    return () => source.close();
  }, []);

  return state;
}
