/** The two small facts a running job puts in the header. */

import { useEffect, useState } from "react";
import { Check, Copy } from "./icons";

/** How long this run has been going. Stops ticking when the stream closes. */
export function Elapsed({ since, running }: { since: number; running: boolean }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const seconds = Math.max(0, Math.round((now - since) / 1000));
  const shown = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return <span className="elapsed">{shown}</span>;
}

/** The id matters when cross-checking a run against the worker's logs or a trace. */
export function CopyJobId({ jobId }: { jobId: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      className="job-id"
      title="Copy job id"
      onClick={() => {
        void navigator.clipboard?.writeText(jobId).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1400);
        });
      }}
    >
      {jobId.slice(0, 8)}
      {copied ? <Check /> : <Copy />}
    </button>
  );
}
