import type { TurnLatency } from "@/lib/types";

const SLOW_MS = 1500;

export function LatencyStrip({ turns }: { turns: TurnLatency[] }) {
  if (turns.length === 0) return null;
  const last = turns[turns.length - 1];
  const max = Math.max(...turns.map((t) => t.total_ms), SLOW_MS);
  return (
    <div className="latency">
      <p>
        Last reply started <span className="num">{seconds(last.total_ms)}</span> after you stopped talking.
      </p>
      <div className="latency-bars" role="img" aria-label={`Reply times for ${turns.length} turns`}>
        {turns.slice(-24).map((t) => (
          <span
            key={t.speech_id}
            data-slow={t.total_ms > SLOW_MS}
            style={{ height: `${Math.max(8, (t.total_ms / max) * 100)}%` }}
            title={`${seconds(t.total_ms)}: end of turn ${t.eou_delay_ms} ms, first word from Claude ${t.llm_ttft_ms} ms, first audio ${t.tts_ttfb_ms} ms`}
          />
        ))}
      </div>
    </div>
  );
}

export function seconds(ms: number) {
  return `${(ms / 1000).toFixed(1)} s`;
}
