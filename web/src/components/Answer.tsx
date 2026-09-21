/**
 * The finished report.
 *
 * It does not arrive on the stream: the orchestrator's output is structured, handed back
 * through `final_result`, so the run emits a tool call and no `text` event. The answer
 * comes from `GET /reports/{id}` instead. A run with a `text` event shows that too — the
 * two are not exclusive, and which one a model produces is the model's choice.
 */

import type { ReportResult } from "../api";

interface Props {
  result: ReportResult;
}

interface Finding {
  statement: string;
  sources?: string[];
}

export function Answer({ result }: Props) {
  const report = result.report;
  if (!report) return null;

  const findings = (report.findings as Finding[] | undefined) ?? [];
  const gaps = (report.gaps as string[] | undefined) ?? [];

  return (
    <section className="answer">
      <span className="label">Answer</span>
      <ul className="findings">
        {findings.map((finding, index) => (
          <li key={index}>
            {finding.statement}
            {finding.sources && finding.sources.length > 0 && (
              <span className="sources"> · {finding.sources.join(", ")}</span>
            )}
          </li>
        ))}
      </ul>

      {gaps.length > 0 && (
        <>
          <span className="label">Gaps</span>
          <ul className="findings gaps">
            {gaps.map((gap, index) => (
              <li key={index}>{gap}</li>
            ))}
          </ul>
        </>
      )}

      {result.spent_usd && <p className="spend">${result.spent_usd}</p>}
    </section>
  );
}
