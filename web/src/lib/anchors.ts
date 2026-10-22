/** The element id a turn scrolls to, shared by the topic list and the turns it points at. */
export function anchorFor(jobId: string): string {
  return `turn-${jobId}`;
}
