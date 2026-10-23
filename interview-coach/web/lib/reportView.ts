// Which parts of the report page show for each report state. Pure, so it is unit-tested with node --test.

import type { Report } from "./types";

export interface ReportView {
  headline: "waiting" | "failed" | "empty" | "ready";
  polling: boolean;
  showSpeech: boolean;
  showTranscript: boolean;
  canRetry: boolean;
}

export function reportView(report: Pick<Report, "status" | "speech" | "transcript">): ReportView {
  const status = report.status;
  const waiting = status === "pending" || status === "in_progress";
  return {
    headline: status === "pending" || status === "in_progress" ? "waiting" : status,
    polling: waiting,
    // How the candidate sounded is useful even when grading failed or there was nothing to grade.
    showSpeech: !waiting && report.speech != null,
    showTranscript: status !== "ready" && report.transcript.length > 0,
    canRetry: status === "failed",
  };
}
