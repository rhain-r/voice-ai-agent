// Interview Coach demo page: browser speech in and out around the ported question plan and analytics.

import { LEVELS, SpeechAnalytics, questionPlan, silenceBeforeTurnEnds } from "./coach.js";
import { canListen, canSpeak, createVoice, now } from "../shared/voice.js";

const ROOT = new URL("../../", import.meta.url);
const FAMILY_NAMES = {
  general: "General", software: "Software engineering", data: "Data and analytics",
  ai_ml: "AI and machine learning", product: "Product management", design: "Design",
};
const LEVEL_NAMES = { intern: "Intern", junior: "Junior", mid: "Mid-level", senior: "Senior", staff: "Staff" };const PACE_MIN = 60;
const PACE_MAX = 230;
const PACE_BAND = [110, 170]; // analytics.py: pace_band

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
const seconds = (s) => `${s.toFixed(1)} s`;
const RANGE_TEXT = `${PACE_BAND[0]} to ${PACE_BAND[1]}`;

const voice = createVoice({ onNotice: (text) => ($("notice").textContent = text), onState: renderStatus });

const c = {
  bank: null,
  setup: null, // {family, level, style, count}
  plan: [],
  index: -1,
  state: "setup", // setup, asking, answering, done
  analytics: null,
  parts: [],
  endTimer: null,
  lastSpokeAt: null, // end of the latest final transcript, while the answer may still continue
  waitFor: null, // seconds of silence that end the answer
};

// -- stages ----------------------------------------------------------------------------------------

function showStage(name) {
  const stage = { setup: "setup", asking: "room", answering: "room", done: "report" }[name];
  for (const id of ["setup", "room", "report"]) {
    $(id).hidden = id !== stage;
    if (id === stage) $(`stage-${id}`).setAttribute("aria-current", "step");
    else $(`stage-${id}`).removeAttribute("aria-current");
  }
}

function setState(state) {
  c.state = state;
  showStage(state);
  renderStatus();
}

// -- setup -----------------------------------------------------------------------------------------

async function loadBank() {
  const res = await fetch(new URL("interview-coach/src/interview_coach/mcp_server/question_bank.json", ROOT));
  if (!res.ok) throw new Error(`question bank: HTTP ${res.status}`);
  c.bank = await res.json();
}

function readSetup() {
  const form = new FormData($("setup-form"));
  return { family: form.get("family"), level: form.get("level"), style: form.get("style"), count: Number(form.get("count")) };
}

async function startInterview() {
  c.setup = readSetup();
  c.plan = questionPlan(c.bank, c.setup.family, c.setup.level, c.setup.style, c.setup.count);
  c.analytics = new SpeechAnalytics();
  c.index = -1;
  voice.speakEnabled = canSpeak && $("speak").checked;
  c.voiced = voice.speakEnabled;
  $("notice").textContent = "";
  setState("asking");
  voice.start();
  const kind = c.setup.style === "mixed" ? "" : ` ${c.setup.style}`;
  $("question-meta").textContent = "Introduction";
  $("question-text").textContent = "Thanks for coming in.";
  $("question-text").focus();
  resetAnswer();
  await say(`Hi, thanks for coming in. This is a ${c.plan.length}-question${kind} interview. ` +
    "Take your time with each answer; silence is fine.");
  await askNext();
}

// -- the interview ---------------------------------------------------------------------------------

async function say(text) {
  const { start, end } = await voice.speak(text);
  c.analytics?.addAgentSpeech(start, end);
}

function resetAnswer() {
  c.parts = [];
  c.lastSpokeAt = null;
  c.waitFor = null;
  clearTimeout(c.endTimer);
  renderAnswer();
}

async function askNext() {
  clearTimeout(c.endTimer);
  if (c.state === "done" || c.state === "setup") return;
  c.index += 1;
  if (c.index >= c.plan.length) return finishInterview();
  const q = c.plan[c.index];
  resetAnswer();
  setState("asking");
  $("question-meta").textContent = `Question ${c.index + 1} of ${c.plan.length}, ${q.style}`;
  $("question-text").textContent = q.text;
  c.analytics.startQuestion(c.index, now());
  const lead = c.index === 0 ? "First question. " : c.index === c.plan.length - 1 ? "Last question. " : "Next question. ";
  await say(lead + q.text);
  if (c.state !== "asking") return;
  setState("answering");
}

function addAnswer(seg) {
  c.analytics.addSegment(seg);
  c.parts.push(seg.text);
  renderAnswer();
}

voice.handler = {
  final(seg) {
    if (c.state !== "answering" || seg.startedWhileSpeaking || voice.isEcho(seg)) return;
    addAnswer(seg);
    // Patient turn-taking: the answer is over only after a silence, a longer one if it trails off.
    c.lastSpokeAt = now();
    c.waitFor = silenceBeforeTurnEnds(c.parts.join(" "));
    clearTimeout(c.endTimer);
    c.endTimer = setTimeout(askNext, c.waitFor * 1000);
  },
  interim(text) {
    if (c.state !== "answering") return;
    clearTimeout(c.endTimer); // still talking
    c.lastSpokeAt = null;
    renderAnswer(text);
  },
};

async function finishInterview({ quiet = false } = {}) {
  clearTimeout(c.endTimer);
  if (c.state === "done") return;
  c.analytics.endQuestions();
  voice.stop();
  voice.cancel();
  setState("done");
  renderReport();
  $("report-heading").focus();
  window.scrollTo({ top: 0 });
  if (!quiet) await say("That's the end of the interview. Thank you. Your report is ready.");
}

// -- room rendering --------------------------------------------------------------------------------

function renderAnswer(interim = "") {
  const text = [...c.parts, interim].filter(Boolean).join(" ");
  const node = $("answer-text");
  node.classList.toggle("is-empty", !text);
  node.textContent = text || (voice.wanted
    ? "Start speaking when you're ready. The interviewer waits until you've said something."
    : "Type your answer below.");
}

function renderStatus() {
  const status = $("room-status");
  let text = "";
  let live = false;
  if (c.state === "asking") text = voice.speaking ? "The interviewer is asking." : "";
  if (c.state === "answering") {
    live = voice.wanted;
    text = voice.wanted ? "Your turn. Take your time." : "Your turn. Type your answer below.";
  }
  status.textContent = text;
  status.dataset.live = String(live);
  const answering = c.state === "answering";
  for (const id of ["done", "repeat"]) $(id).disabled = !answering;
  $("typed").disabled = !answering;
  $("answer-form").querySelector("button").disabled = !answering;
}

// The patience meter: how much of the silence that ends your answer has passed.
function renderPatience() {
  if (c.state !== "answering") {
    $("patience-fill").style.transform = "scaleX(0)";
    $("patience-text").textContent = "";
    return;
  }
  if (c.lastSpokeAt == null) {
    $("patience-fill").style.transform = "scaleX(0)";
    $("patience-text").textContent = c.parts.length ? "Listening." : voice.wanted
      ? "The next question waits until you've answered." : "";
    return;
  }
  const waited = Math.min(now() - c.lastSpokeAt, c.waitFor);
  $("patience-fill").style.transform = `scaleX(${waited / c.waitFor})`;
  const last = c.parts.join(" ").toLowerCase().replace(/[^a-z\s']/g, " ").trim().split(/\s+/).at(-1);
  $("patience-text").textContent = c.waitFor > 3
    ? `You trailed off on “${last}”, so the interviewer waits longer: ${seconds(waited)} of ${seconds(c.waitFor)}.`
    : `Pause ${seconds(waited)} of ${seconds(c.waitFor)} before the next question.`;
}

// -- report ----------------------------------------------------------------------------------------

function paceFigure(a) {
  const pct = (wpm) => `${(100 * (Math.min(PACE_MAX, Math.max(PACE_MIN, wpm)) - PACE_MIN)) / (PACE_MAX - PACE_MIN)}%`;
  const band = el("span", { className: "scale-band" });
  band.style.left = pct(PACE_BAND[0]);
  band.style.width = `calc(${pct(PACE_BAND[1])} - ${pct(PACE_BAND[0])})`;
  const mark = el("span", { className: "scale-mark" });
  mark.style.left = pct(a.wpm);
  const scale = el("div", { className: "scale" }, el("span", { className: "scale-track" }), band, mark);
  scale.setAttribute("aria-hidden", "true");
  return el("figure", { className: "pace" }, scale,
    el("figcaption", {}, el("strong", { textContent: `${Math.round(a.wpm)} words per minute, ${a.paceBand}.` }),
      ` The shaded band is the conversational range, ${RANGE_TEXT}.`));
}

function metricsTable(a, timed) {
  const tics = Object.entries(a.verbalTics).map(([w, n]) => `“${w}” ${n}×`).join(", ") || "None";
  const rows = [
    ["Words", timed ? `${a.wordCount} in ${seconds(a.durationS)}` : String(a.wordCount)],
    ["Filler words (um, uh, er)", !a.fillerCount ? "None"
      : timed ? `${a.fillerCount}, or ${a.fillersPerMin} per minute` : String(a.fillerCount)],
    ["Verbal habits", tics],
    ["Longest pause", timed ? seconds(a.longestPauseS) : "Not measured for typed answers"],
    ["Pauses over 3 seconds", timed ? String(a.pausesOver3s) : "Not measured for typed answers"],
    ["Thinking time before answering", timed && a.thinkingTimeS != null ? seconds(a.thinkingTimeS) : "Not measured"],
  ];
  return el("table", { className: "metrics" }, el("tbody", {}, ...rows.map(([k, v]) =>
    el("tr", {}, el("th", { scope: "row", textContent: k }), el("td", { textContent: v })))));
}

function coversChecklist(q, i) {
  const count = el("p", { className: "covers-count", textContent: `0 of ${q.good_answer_covers.length} ticked` });
  count.setAttribute("aria-live", "polite");
  const boxes = q.good_answer_covers.map((point) => {
    const box = el("input", { type: "checkbox", name: `covers-${i}` });
    box.addEventListener("change", () => {
      const ticked = boxes.filter((b) => b.querySelector("input").checked).length;
      count.textContent = `${ticked} of ${boxes.length} ticked`;
    });
    return el("label", {}, box, point[0].toUpperCase() + point.slice(1));
  });
  return el("fieldset", { className: "covers" }, el("legend", { textContent: "A strong answer covers" }),
    el("p", { className: "covers-hint", textContent: "Tick what your answer included." }), ...boxes, count);
}

function renderReport() {
  const m = c.analytics.sessionMetrics();
  const answered = m.answers.filter((a) => a.wordCount).length;
  const spoken = m.answers.some((a) => a.durationS > 0);
  const date = new Intl.DateTimeFormat(undefined, { dateStyle: "long" }).format(new Date());
  const level = c.setup.level === "mid" ? "mid-level" : `${c.setup.level} level`;
  $("report-meta").textContent = `${FAMILY_NAMES[c.setup.family]}, ${level}, ${c.setup.style} format. ` +
    `${answered} of ${c.plan.length} questions answered. ${date}.`;

  const notTimed = "Not measured for typed answers";
  const share = !spoken ? [notTimed, "n/a"] : !c.voiced ? ["The interviewer's voice was off", "n/a"]
    : ["Your speech against the interviewer's", `${Math.round(m.talkRatio * 100)}%`];
  const items = [
    ["Average pace", spoken ? `${Math.round(m.avgWpm)} wpm` : "n/a", spoken ? `Conversational is ${RANGE_TEXT}` : notTimed],
    ["Filler words", spoken ? `${m.fillersPerMin} / min` : "n/a", spoken ? "Um, uh and er per minute of speech" : notTimed],
    ["Your share of the talking", share[1], share[0]],
    ["Average thinking time", spoken && m.avgThinkingTimeS != null ? seconds(m.avgThinkingTimeS) : "n/a",
      spoken ? "From the question ending to your first word" : notTimed],
  ];
  $("summary").replaceChildren(...(spoken ? items.map(([label, value, note]) =>
    el("div", {}, el("dt", { textContent: label }), el("dd", {}, value, el("span", { textContent: note }))))
    : [el("div", {}, el("dt", { textContent: "Speech measures" }), el("dd", { className: "summary-plain",
      textContent: "Not available for typed answers. Answer out loud in Chrome, Edge or Safari to see your pace, " +
        "filler rate, share of the talking and thinking time." }))]));

  const asked = c.plan.slice(0, Math.min(c.plan.length, c.index + 1));
  if (!asked.length) {
    $("answers").replaceChildren(el("p", { className: "report-note", textContent: "The interview ended before the first question." }));
    return;
  }
  $("answers").replaceChildren(...asked.map((q, i) => {
    const a = m.answers[i] ?? { wordCount: 0 };
    const timed = a.durationS > 0;
    const article = el("article", { className: "answer-report sheet" },
      el("h2", { textContent: `Question ${i + 1}, ${q.style}` }),
      el("p", { className: "ar-question", textContent: q.text }));
    if (a.wordCount) {
      article.append(el("p", { className: "ar-said", textContent: `“${a.transcript}”` }));
      if (timed) article.append(paceFigure(a));
      article.append(metricsTable(a, timed));
    } else {
      article.append(el("p", { className: "ar-said is-empty", textContent: "No answer was recorded for this question." }));
    }
    article.append(coversChecklist(q, i));
    return article;
  }));
}

// -- start -----------------------------------------------------------------------------------------

function wire() {
  for (const level of LEVELS) $("level").append(el("option", { value: level, textContent: LEVEL_NAMES[level] }));
  $("level").value = "mid";

  $("setup-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (c.bank) startInterview();
  });
  $("done").addEventListener("click", askNext);
  $("repeat").addEventListener("click", async () => {
    clearTimeout(c.endTimer);
    c.lastSpokeAt = null;
    setState("asking");
    await say(c.plan[c.index].text);
    if (c.state === "asking") setState("answering");
  });
  $("end").addEventListener("click", () => finishInterview());
  $("answer-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("typed").value.trim();
    if (!text || c.state !== "answering") return;
    $("typed").value = "";
    addAnswer({ text, start: now(), end: now() });
    askNext();
  });
  $("again").addEventListener("click", () => {
    setState("setup");
    $("family").focus();
  });
  $("print").addEventListener("click", () => window.print());
  $("reload").addEventListener("click", () => location.reload());

  if (!canListen) {
    $("mic-note").textContent = "This browser can't listen (Firefox has no speech recognition), so you'll type " +
      "your answers. Chrome, Edge and Safari can listen; typed answers leave the timing measures out of the report.";
  }
  if (!canSpeak) {
    $("speak").checked = false;
    $("speak").disabled = true;
  }
}

async function main() {
  wire();
  setState("setup");
  try {
    await loadBank();
    $("start").disabled = false;
    $("start").textContent = "Start interview";
  } catch (err) {
    console.error(err);
    $("start").textContent = "Questions unavailable";
    $("setup-error").hidden = false;
  }
  setInterval(renderPatience, 100);
}

main();
