import type { Dimension } from "@/lib/types";

export const DIMENSION_LABEL: Record<Dimension, string> = {
  structure: "Structure",
  specificity: "Specificity",
  impact: "Impact",
  relevance: "Relevance",
  communication: "Communication",
};

const ORDER: Dimension[] = ["structure", "specificity", "impact", "relevance", "communication"];

export function DimensionBars({ averages, weakest }: { averages: Record<Dimension, number>; weakest: Dimension }) {
  return (
    <div className="dims" role="list">
      {ORDER.map((d) => {
        const value = averages[d] ?? 0;
        return (
          <div className="dim" role="listitem" key={d} data-weakest={d === weakest}>
            <span>{DIMENSION_LABEL[d]}</span>
            <span className="track" aria-label={`${DIMENSION_LABEL[d]}: ${value} out of 5`}>
              <span className="value" style={{ width: `${(value / 5) * 100}%` }} />
              <span className="ticks" aria-hidden>
                {[0, 1, 2, 3, 4, 5].map((t) => (
                  <i key={t} />
                ))}
              </span>
            </span>
            <span className="num">{value.toFixed(1)}</span>
          </div>
        );
      })}
    </div>
  );
}
