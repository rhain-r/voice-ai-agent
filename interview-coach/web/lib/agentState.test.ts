import assert from "node:assert/strict";
import { test } from "node:test";
import { describeAgentState } from "./agentState.ts";

test("after the interviewer leaves, the page says the interview is over, not 'connecting'", () => {
  const { label } = describeAgentState("disconnected", false);
  assert.equal(label, "The interview is over");
  assert.doesNotMatch(label, /connecting/i);
});

test("listening with the candidate silent invites them to take their time", () => {
  assert.deepEqual(describeAgentState("listening", false), {
    label: "Your turn",
    hint: "Take your time. Pauses to think are fine.",
  });
});

test("listening while the candidate talks shows they are answering", () => {
  assert.equal(describeAgentState("listening", true).label, "You're answering");
});

test("initial states read as connecting", () => {
  for (const state of ["connecting", "initializing", "pre-connect-buffering"]) {
    assert.match(describeAgentState(state, false).label, /connecting/i);
  }
});
