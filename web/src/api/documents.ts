/** Documents behind the Knowledge chip. */

import { del, get, post, request } from "./client";

/** `uploaded` and `parsing` lock the knowledge base against questions. */
export type DocumentState = "uploaded" | "parsing" | "ready" | "failed";

export interface DocumentRow {
  id: number;
  filename: string;
  mime: string;
  size: number;
  status: DocumentState;
  fail_reason: string | null;
  enabled: boolean;
  pages: number | null;
}

/** One passage an answer cites. `page` is null for DOCX and Markdown. */
export interface SourceRef {
  label: string;
  chunk_id: number;
  document_id: number;
  filename: string;
  mime: string;
  page: number | null;
  /** The last page the passage runs onto; the quote may sit there rather than on `page`. */
  page_end?: number | null;
  section: string;
  /** The words the answer cited, checked to occur in the passage. */
  quote?: string;
}

export interface Passage {
  id: number;
  document_id: number;
  filename: string;
  text: string;
  section_path: string;
  page_start: number | null;
}

export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;

/** What GET /documents/status sends on every change: the whole list, and whether
 *  anything is still being processed. */
export interface DocumentStatus {
  busy: boolean;
  documents: DocumentRow[];
}

export function uploadDocument(file: File): Promise<DocumentRow> {
  const body = new FormData();
  body.append("file", file);
  return post<DocumentRow>("/documents", body);
}

export const updateDocument = (
  id: number,
  patch: { enabled?: boolean; filename?: string },
): Promise<DocumentRow> => request<DocumentRow>("PATCH", `/documents/${id}`, patch);

export const deleteDocument = (id: number): Promise<void> => del(`/documents/${id}`);

export const fetchSourceUrl = (documentId: number): Promise<string> =>
  get<{ url: string }>(`/documents/${documentId}/source`).then((found) => found.url);

export const fetchPassage = (chunkId: number): Promise<Passage> =>
  get<Passage>(`/chunks/${chunkId}`);
