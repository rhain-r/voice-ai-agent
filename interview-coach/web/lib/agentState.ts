// What the speaker ring says for each agent state. Pure, so it is unit-tested with node --test.

export function describeAgentState(state: string, candidateTalking: boolean): { label: string; hint?: string } {
  switch (state) {
    case "speaking":
      return { label: "Interviewer is speaking", hint: "You can interrupt if you need to." };
    case "thinking":
      return { label: "Interviewer is thinking" };
    case "listening":
      return candidateTalking
        ? { label: "You're answering" }
        : { label: "Your turn", hint: "Take your time. Pauses to think are fine." };
    case "disconnected":
      return { label: "The interview is over", hint: "Opening your scorecard…" };
    case "failed":
      return { label: "The interviewer couldn't join", hint: "Check that the agent worker is running." };
    default:
      return { label: "Connecting to your interviewer…" };
  }
}
