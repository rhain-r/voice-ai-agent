"use client";

import type { AgentState } from "@livekit/components-react";
import { describeAgentState } from "@/lib/agentState";

const SPEAKING_THRESHOLD = 0.06;

export function SpeakerRing({
  state,
  agentVolume,
  micVolume,
}: {
  state: AgentState;
  agentVolume: number;
  micVolume: number;
}) {
  const candidateTalking = state === "listening" && micVolume > SPEAKING_THRESHOLD;
  const who =
    state === "speaking" ? "interviewer" : state === "thinking" ? "thinking" : candidateTalking ? "candidate" : "idle";
  const level = who === "interviewer" ? agentVolume : who === "candidate" ? micVolume : 0;

  const { label, hint } = describeAgentState(state, candidateTalking);
  return (
    <>
      <div
        className="ring"
        data-who={who}
        style={{ ["--level" as string]: Math.min(1, level * 2).toFixed(2) }}
        aria-hidden
      />
      <p className="ring-label" aria-live="polite">
        {label}
      </p>
      {hint && <p className="ring-hint">{hint}</p>}
    </>
  );
}
