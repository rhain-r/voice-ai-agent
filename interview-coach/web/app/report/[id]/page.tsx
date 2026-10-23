"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AnswerCard } from "@/components/AnswerCard";
import { DIMENSION_LABEL, DimensionBars } from "@/components/DimensionBars";
import { seconds } from "@/components/LatencyStrip";
import { ApiError, getReport, retryReport } from "@/lib/api";
import type { Dimension, Report } from "@/lib/types";

const POLL_MS = 2000;

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setReport(await getReport(id));
      setError(null);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 404
          ? "We couldn't find that interview."
          : e instanceof Error
            ? e.message
            : "Couldn't load the scorecard.",
      );
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const waiting = report?.status === "pending" || report?.status === "in_progress";
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, load]);

  if (error) {
    return (
      <main className="page">
        <div className="notice" role="alert">
          <h2>{error}</h2>
          <p>
            <Link href="/">Start a new interview</Link>
          </p>
        </div>
      </main>
    );
  }
  if (!report) return null;

  const setup = report.session.setup;
  return (
    <main className="page">
      <p className="muted">
        <Link href="/">New interview</Link>
      </p>
      {waiting && <Waiting report={report} />}
      {report.status === "failed" && <Failed report={report} onRetry={() => retryReport(id).then(load)} />}
      {report.status === "ready" && report.scorecard && <Ready report={report} />}
      {report.status !== "ready" && report.transcript.length > 0 && (
        <section className="section">
          <h2>Transcript</h2>
          <ol className="transcript" style={{ marginTop: "1rem" }}>
            {report.transcript.map((t, i) => (
              <li key={i} data-who={t.role === "assistant" ? "interviewer" : "candidate"}>
                <div className="speaker">{t.role === "assistant" ? "Interviewer" : "You"}</div>
                <p>{t.text}</p>
              </li>
            ))}
          </ol>
        </section>
      )}
      <p className="footnote">
        {setup.role}, {setup.level} level, {setup.style} questions.
      </p>
    </main>
  );
}

function Waiting({ report }: { report: Report }) {
  return (
    <div className="narrow" aria-live="polite">
      <h1>{report.status === "pending" ? "Writing your scorecard…" : "Wrapping up your interview…"}</h1>
      <p className="lede">
        Each answer is graded separately against the rubric, then turned into a short coaching plan. This usually takes
        under a minute.
      </p>
    </div>
  );
}

function Failed({ report, onRetry }: { report: Report; onRetry: () => Promise<void> }) {
  const [retrying, setRetrying] = useState(false);
  return (
    <div className="narrow">
      <h1>The scorecard didn&apos;t finish.</h1>
      <p className="lede">Your transcript and speech metrics are saved. Grading failed with: {report.error}</p>
      <div className="actions">
        <button
          className="button"
          type="button"
          disabled={retrying}
          onClick={() => {
            setRetrying(true);
            void onRetry().finally(() => setRetrying(false));
          }}
        >
          {retrying ? "Retrying…" : "Retry grading"}
        </button>
      </div>
    </div>
  );
}

function Ready({ report }: { report: Report }) {
  const sc = report.scorecard!;
  const setup = report.session.setup;
  const strongest = (Object.entries(sc.dimension_averages) as [Dimension, number][]).reduce((a, b) =>
    b[1] > a[1] ? b : a,
  )[0];
  const grades = new Map(sc.graded.map((g) => [g.index, g.grade]));
  const speech = report.speech;

  return (
    <>
      <h1 className="verdict">
        You scored <span className="score">{sc.overall}</span> out of 100 as a {setup.level} {setup.role}.
      </h1>
      <p className="lede">
        Strongest on {DIMENSION_LABEL[strongest].toLowerCase()}, weakest on{" "}
        {DIMENSION_LABEL[sc.weakest_dimension].toLowerCase()}.
        {report.session.completion_status === "partial" && " The interview ended early, so only answered questions count."}
      </p>

      <div className="report-grid">
        <section aria-labelledby="dims-title">
          <h2 id="dims-title">Across your answers</h2>
          <DimensionBars averages={sc.dimension_averages} weakest={sc.weakest_dimension} />
        </section>
        {speech && (
          <section aria-labelledby="sound-title">
            <h2 id="sound-title">How you sounded</h2>
            <dl className="facts">
              <dt>Pace</dt>
              <dd>{Math.round(speech.avg_wpm)} words per minute</dd>
              <dt>Filler words</dt>
              <dd>{speech.fillers_per_min.toFixed(1)} per minute</dd>
              <dt>Time to start</dt>
              <dd>
                {speech.avg_thinking_time_s != null ? `${speech.avg_thinking_time_s.toFixed(1)} s on average` : "n/a"}
              </dd>
              <dt>You talked</dt>
              <dd>{Math.round(speech.talk_ratio * 100)}% of the time</dd>
            </dl>
          </section>
        )}
      </div>

      <section className="section coaching" aria-labelledby="fix-title">
        <h2 id="fix-title">What to work on</h2>
        <ol>
          {sc.coaching.top_fixes.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ol>
        <h3 style={{ marginTop: "2rem" }}>Your weakest answer, rewritten</h3>
        <p className="rewrite">{sc.coaching.rewritten_answer}</p>
        <h3 style={{ marginTop: "2rem" }}>Practice drill</h3>
        <p className="lede" style={{ color: "inherit" }}>
          {sc.coaching.practice_drill}
        </p>
      </section>

      <section className="section" aria-labelledby="qs-title">
        <h2 id="qs-title">Question by question</h2>
        <ol className="answers">
          {report.qa_items.map((item) => (
            <AnswerCard key={item.index} item={item} grade={grades.get(item.index)} />
          ))}
        </ol>
      </section>

      {report.latency && report.latency.turns > 0 && (
        <p className="footnote num">
          Response time: the interviewer started replying in {seconds(report.latency.p50_ms)} on a typical turn and{" "}
          {seconds(report.latency.p95_ms)} at the slowest, across {report.latency.turns} replies.
        </p>
      )}
    </>
  );
}
