/** Citation markers while an answer streams. */

const MARKER = /\[c\d+\]/g;
/** The end of a chunk that may be the start of a marker still being written. */
const PARTIAL = /\[(c\d*)?$/;

/** The streamed text as it should show: no markers, nor half of one at the end. */
export function hideMarkers(text: string): string {
  return text.replace(MARKER, "").replace(PARTIAL, "");
}
