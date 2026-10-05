/**
 * Citation markers while a Knowledge answer streams.
 *
 * The model writes `[c2]` after a claim, and the server only knows which markers are real
 * once the answer is finished and checked. So every marker is hidden while the text
 * streams, and the checked answer replaces it at the end: a wrong marker is never seen.
 */

const MARKER = /\[c\d+\]/g;
/** The end of a chunk that may be the start of a marker still being written. */
const PARTIAL = /\[(c\d*)?$/;

/** The streamed text as it should show: no markers, nor half of one at the end. */
export function hideMarkers(text: string): string {
  return text.replace(MARKER, "").replace(PARTIAL, "");
}

/** The agent whose streamed text carries citation markers. */
export const CITING_AGENT = "answerer";
