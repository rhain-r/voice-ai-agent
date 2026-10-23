"use client";

import type { AgentState } from "@livekit/components-react";

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

  const { label, hint } = describe(state, candidateTalking);
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

function describe(state: AgentState, candidateTalking: boolean): { label: string; hint?: string } {
  switch (state) {
    case "speaking":
      return { label: "Interviewer is speaking", hint: "You can interrupt if you need to." };
    case "thinking":
      return { label: "Interviewer is thinking" };
    case "listening":
      return candidateTalking
        ? { label: "You're answering" }
        : { label: "Your turn", hint: "Take your time. Pauses to think are fine." };
    case "failed":
      return { label: "The interviewer couldn't join", hint: "Check that the agent worker is running." };
    default:
      return { label: "Connecting to your interviewer…" };
  }
}
