import assert from "node:assert/strict";
import { test } from "node:test";
import { reportView } from "./reportView.ts";

const speech = { avg_wpm: 140, fillers_per_min: 2, talk_ratio: 0.6, avg_thinking_time_s: 2 };

test("a failed scorecard still shows how the candidate sounded", () => {
  const view = reportView({ status: "failed", speech, transcript: [{ role: "user", text: "hi", at: 1 }] });
  assert.equal(view.headline, "failed");
  assert.equal(view.showSpeech, true);
  assert.equal(view.showTranscript, true);
});

test("an interview with nothing answered is its own state, with speech shown and no retry", () => {
  const view = reportView({ status: "empty", speech, transcript: [] });
  assert.equal(view.headline, "empty");
  assert.equal(view.showSpeech, true);
  assert.equal(view.canRetry, false);
});

test("only a failed report can be retried", () => {
  assert.equal(reportView({ status: "failed", speech: null, transcript: [] }).canRetry, true);
  assert.equal(reportView({ status: "ready", speech, transcript: [] }).canRetry, false);
});

test("pending and in-progress reports keep polling and hide speech until ready", () => {
  for (const status of ["pending", "in_progress"] as const) {
    const view = reportView({ status, speech: null, transcript: [] });
    assert.equal(view.polling, true);
    assert.equal(view.headline, "waiting");
  }
});
