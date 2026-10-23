"use client";

import type { TextStreamData } from "@livekit/components-react";
import { useEffect, useRef } from "react";

export function Transcript({ entries, agentIdentity }: { entries: TextStreamData[]; agentIdentity?: string }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), [entries]);

  const visible = entries.filter((e) => e.text.trim());
  if (visible.length === 0) {
    return <p className="empty-note">The conversation will appear here as you talk.</p>;
  }

  return (
    <ol className="transcript" aria-label="Transcript">
      {visible.map((entry) => {
        const isAgent = entry.participantInfo.identity === agentIdentity;
        const final = entry.streamInfo.attributes?.["lk.transcription_final"] !== "false";
        return (
          <li key={entry.streamInfo.id} data-who={isAgent ? "interviewer" : "candidate"}>
            <div className="speaker">{isAgent ? "Interviewer" : "You"}</div>
            <p className={final ? undefined : "interim"}>{entry.text}</p>
          </li>
        );
      })}
      <li ref={end} aria-hidden style={{ border: 0, padding: 0 }} />
    </ol>
  );
}
