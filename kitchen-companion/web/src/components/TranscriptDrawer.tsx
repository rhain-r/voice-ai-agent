import { useEffect, useRef } from "react";
import type { Latency, TranscriptLine } from "../lib/types";

type Props = { open: boolean; lines: TranscriptLine[]; onClose: () => void };

function chip({ path, ms }: Latency): string {
  const time = ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  return `${path} · ${time}`;
}

// Everything the mic picked up: lines Chef answered in full contrast, overheard ones greyed,
// and how fast each reply started (fast path vs. LLM).
export function TranscriptDrawer({ open, lines, onClose }: Props) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) end.current?.scrollIntoView({ block: "end" });
  }, [open, lines.length]);

  return (
    <aside className={open ? "drawer open" : "drawer"} aria-hidden={!open} aria-label="Transcript">
      <div className="drawer-head">
        <h2>What Chef heard</h2>
        <button type="button" className="text-button" onClick={onClose} tabIndex={open ? 0 : -1}>
          Close
        </button>
      </div>
      {lines.length === 0 ? (
        <p className="drawer-empty">Nothing yet. Start a sentence with “Chef” and it shows up here.</p>
      ) : (
        <ol className="lines">
          {lines.map((line) => (
            <li key={line.id} className={`line ${line.kind}`}>
              <span className="line-who">{line.kind === "reply" ? "Chef" : line.kind === "heard" ? "You" : "Overheard"}</span>
              <span className="line-text">{line.text}</span>
              {line.latency && <span className={`chip ${line.latency.path}`}>{chip(line.latency)}</span>}
            </li>
          ))}
        </ol>
      )}
      <div ref={end} />
    </aside>
  );
}
