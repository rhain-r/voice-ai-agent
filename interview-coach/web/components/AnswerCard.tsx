import { DIMENSION_LABEL } from "@/components/DimensionBars";
import type { AnswerGrade, AnswerMetrics, Dimension, QAItem } from "@/lib/types";

export function AnswerCard({ item, grade }: { item: QAItem; grade?: AnswerGrade }) {
  return (
    <li className="answer">
      <h3>{item.question}</h3>
      {grade ? (
        <>
          <p className="verdict-line">{grade.one_line_verdict}</p>
          <div className="scores-inline">
            {(Object.keys(DIMENSION_LABEL) as Dimension[]).map((d) => (
              <span key={d}>
                {DIMENSION_LABEL[d]} <strong className="num">{grade.scores[d]}</strong>
              </span>
            ))}
          </div>
          {grade.evidence_quotes.slice(0, 2).map((q) => (
            <blockquote key={q}>&ldquo;{q}&rdquo;</blockquote>
          ))}
          <div className="two-col">
            <div>
              <strong>What worked</strong>
              <ul>
                {grade.strengths.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
            <div>
              <strong>Try next time</strong>
              <ul>
                {grade.improvements.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          </div>
        </>
      ) : (
        <p className="verdict-line muted">Skipped. There was no answer to grade.</p>
      )}
      <SoundLine metrics={item.metrics} />
    </li>
  );
}

function SoundLine({ metrics }: { metrics: Partial<AnswerMetrics> }) {
  if (!metrics.word_count) return null;
  const parts = [
    `${Math.round(metrics.wpm ?? 0)} words per minute (${metrics.pace_band})`,
    `${metrics.filler_count ?? 0} filler ${metrics.filler_count === 1 ? "word" : "words"}`,
    `longest pause ${(metrics.longest_pause_s ?? 0).toFixed(1)} s`,
  ];
  if (metrics.thinking_time_s != null) parts.push(`${metrics.thinking_time_s.toFixed(1)} s to start answering`);
  return <p className="sound num">{parts.join(", ")}.</p>;
}
