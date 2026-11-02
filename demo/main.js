// Browser speech in and out, plus the page wiring for both agents.

import {
  RecipeSession, TimerService, announcementText, decide, fastReply, isStopWord, parse, recipeFromBundle,
  sentence, speakable, toolRoute,
} from "./kitchen.js";
import { LEVELS, SpeechAnalytics, questionPlan, silenceBeforeTurnEnds } from "./coach.js";

const ROOT = new URL("../", import.meta.url);
const RECIPE_IDS = ["fluffy-pancakes", "chicken-stir-fry", "chocolate-chip-cookies", "garlic-butter-pasta",
  "spinach-feta-omelette", "tomato-soup"];
const FOLLOWUP_S = 8; // attention.py: AttentionConfig.followup_window_s
const BUTTON_TTL_S = 10; // attention.py: BUTTON_TTL_S
const CONTINUATION_S = 3; // attention.py: CONTINUATION_S

const $ = (id) => document.getElementById(id);
const now = () => performance.now() / 1000;
const el = (tag, text) => Object.assign(document.createElement(tag), { textContent: text ?? "" });

// -- voice: browser speech recognition and speech synthesis ----------------------------------------

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const tts = window.speechSynthesis;

const voice = {
  handler: null, // {final(seg), interim(text)} of the active agent
  wanted: false,
  running: false,
  speaking: false,
  utteranceStart: null,
  lastHeardAt: -Infinity,
  recent: [], // [{words, end}] of recent replies, to drop our own voice coming back through the mic
  rec: null,
  onstate: () => {},

  start() {
    if (!Recognition) return;
    this.wanted = true;
    if (!this.rec) {
      const rec = new Recognition();
      rec.lang = "en-US";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onstart = () => { this.running = true; this.onstate(); };
      rec.onresult = (e) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const text = e.results[i][0].transcript.trim();
          if (this.utteranceStart == null) {
            this.utteranceStart = now();
            this.startedWhileSpeaking = this.speaking;
          }
          this.lastHeardAt = now();
          if (e.results[i].isFinal) {
            const seg = { text, start: this.utteranceStart, end: now(), startedWhileSpeaking: this.startedWhileSpeaking };
            this.utteranceStart = null;
            if (text) this.handler?.final(seg);
          } else {
            this.handler?.interim?.(text);
          }
        }
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          this.wanted = false;
          notice("Microphone access was blocked. Allow it in the address bar, or type instead.");
        }
      };
      rec.onend = () => {
        this.running = false;
        this.onstate();
        if (this.wanted) setTimeout(() => this.wanted && this.safeStart(), 250);
      };
      this.rec = rec;
    }
    this.safeStart();
  },

  safeStart() {
    try { this.rec.start(); } catch { /* already started */ }
  },

  stop() {
    this.wanted = false;
    this.rec?.stop();
    this.onstate();
  },

  // Our own reply picked up by the microphone: mostly the same words, heard during or just after it.
  isEcho(seg) {
    const heard = seg.text.toLowerCase().match(/[a-z0-9']+/g) ?? [];
    if (!heard.length) return false;
    return this.recent.some((r) => seg.start <= r.end + 4 &&
      heard.filter((w) => r.words.has(w)).length / heard.length >= 0.7);
  },

  // Speaks and resolves with when speech started and ended (seconds on the page clock).
  speak(text, onStart) {
    return new Promise((resolve) => {
      const asked = now();
      const words = new Set(text.toLowerCase().match(/[a-z0-9']+/g) ?? []);
      if (!$("speak").checked || !tts) {
        onStart?.(now());
        this.recent = [{ words, end: now() }];
        resolve({ start: asked, end: now() });
        return;
      }
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "en-US";
      u.rate = 1.05;
      u.voice = tts.getVoices().find((v) => v.lang === "en-US" && v.localService) ?? null;
      let started = null;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(fallback);
        this.speaking = false;
        this.recent = [{ words, end: now() }];
        this.onstate();
        resolve({ start: started ?? asked, end: now() });
      };
      u.onstart = () => {
        started = now();
        this.speaking = true;
        this.recent = [{ words, end: Infinity }];
        this.onstate();
        onStart?.(started);
      };
      u.onend = finish;
      u.onerror = finish;
      // Some browsers never fire onend without an audio device; don't wait on them forever.
      const fallback = setTimeout(() => { if (started == null) onStart?.(now()); finish(); }, 2500 + text.length * 90);
      tts.cancel();
      tts.speak(u);
    });
  },

  cancel() {
    tts?.cancel();
  },
};

function notice(text) {
  $("notice").textContent = text;
}

// -- Kitchen Companion -----------------------------------------------------------------------------

const k = {
  recipes: new Map(),
  session: new RecipeSession(),
  timers: new TimerService(),
  windowOpenUntil: -Infinity,
  buttonUntil: -Infinity,
  announcements: [], // [{text, queuedAt}]
};

async function loadRecipes() {
  const select = $("k-recipe");
  for (const id of RECIPE_IDS) {
    const res = await fetch(new URL(`kitchen-companion/src/kitchen_companion/recipes/library/${id}.json`, ROOT));
    const recipe = recipeFromBundle(await res.json());
    k.recipes.set(id, recipe);
    select.append(Object.assign(el("option", recipe.title), { value: id }));
  }
}

function kLog(heard, route, reply) {
  const row = document.createElement("tr");
  const cells = [heard, route, reply, ""].map((t) => el("td", t));
  row.append(...cells);
  $("k-log").prepend(row);
  return cells[3];
}

async function kRespond(heard, route, reply, heardAt) {
  const latencyCell = kLog(heard, route, reply);
  await voice.speak(speakable(reply), (start) => {
    latencyCell.textContent = `${Math.max(0, Math.round((start - heardAt) * 1000))} ms`;
  });
  // attention.py: the bot finishing a sentence opens the follow-up window.
  k.windowOpenUntil = now() + FOLLOWUP_S;
  renderKitchen();
}

function kitchenLine(seg, typed = false) {
  const t = now();
  if (!typed && voice.isEcho(seg)) return;
  if (!typed && seg.startedWhileSpeaking && !isStopWord(seg.text) && !/^\W*(?:hey |ok |okay )?chef\b/i.test(seg.text)) {
    return; // the microphone hearing Chef talk; only a stop word or the wake word cuts in
  }
  const d = decide(seg.text, {
    now: t, windowOpenUntil: k.windowOpenUntil, buttonArmed: t <= k.buttonUntil, botSpeaking: voice.speaking,
  });
  if (!d.engaged) {
    if (d.reason !== "empty") kLog(seg.text, "overheard: not addressed to Chef, ignored", "");
    return;
  }
  k.buttonUntil = -Infinity;
  if (!d.text) {
    kRespond(seg.text, "attention gate: wake word only", "Yes?", t);
    return;
  }
  // STT may split one utterance into several finals; keep listening for the rest of it.
  k.windowOpenUntil = Math.max(k.windowOpenUntil, t + CONTINUATION_S);

  const intent = parse(d.text);
  if (intent) {
    const wasSpeaking = voice.speaking;
    const reply = fastReply(intent, k.session, k.timers);
    if (reply !== false) {
      // Kitchen noise doesn't cut Chef off: only a stop word or a command of 2+ words does.
      if (intent.kind === "stop" || (wasSpeaking && d.text.split(/\s+/).length >= 2)) voice.cancel();
      renderKitchen();
      if (reply) kRespond(seg.text, `fast path (code, no LLM): ${intent.kind}`, reply, t);
      else kLog(seg.text, `fast path (code, no LLM): ${intent.kind}`, "(stops talking)");
      return;
    }
  }
  const tool = toolRoute(d.text);
  if (tool) {
    let reply;
    if (tool.tool === "scale_recipe") {
      reply = k.session.scaleTo(tool.servings);
    } else {
      const answer = k.session.ingredient(tool.name);
      reply = answer.found ? sentence(answer.text) + "." : answer.text;
    }
    kRespond(seg.text, `tool: ${tool.tool}`, reply, t);
    return;
  }
  kRespond(seg.text, "LLM: Claude Haiku in the full app, not called here",
    "That one needs Claude, which this demo doesn't call. Try next, back, a timer, or how much of something.", t);
}

const kitchenHandler = {
  final: (seg) => kitchenLine(seg),
  // A stop word cuts Chef off as soon as it's heard, before the transcript is final.
  interim: (text) => { if (voice.speaking && isStopWord(text)) voice.cancel(); },
};

function renderKitchen() {
  const s = k.session;
  if (s.recipe) {
    $("k-step").textContent = `${s.recipe.title}, step ${s.index + 1} of ${s.recipe.steps.length}: ` +
      s.recipe.steps[s.index].text;
    $("k-servings").textContent = `${s.servings} servings`;
    $("k-ingredients").replaceChildren(...s.recipe.ingredients.map((i) => el("li", s.ingredientText(i))));
  }
  renderTimers();
}

function renderTimers() {
  const list = k.timers.list();
  const items = list.map((t) => {
    const li = el("li");
    const left = Math.max(0, Math.ceil(t.endsAt - now()));
    const clock = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    li.append(t.state === "due" ? `${t.label}: done (say "got it" or "stop") ` : `${t.label}: ${clock} `);
    const cancel = el("button", "Cancel");
    cancel.onclick = () => { k.timers.cancel(t.id); renderTimers(); };
    li.append(cancel);
    return li;
  });
  $("k-timers").replaceChildren(...(items.length ? items : [el("li", "None running.")]));
}

function kitchenTick() {
  for (const [due, reminder] of k.timers.tick()) {
    const text = announcementText(due.map((t) => t.label), reminder ? null : k.session.nextStepText(), reminder);
    k.announcements.push({ text, queuedAt: now() });
  }
  // timers.py AnnouncementGate: wait until neither the cook nor Chef is talking (at most 8 s).
  const next = k.announcements[0];
  const quiet = !voice.speaking && now() - voice.lastHeardAt > 1;
  if (next && (quiet || now() - next.queuedAt > 8)) {
    k.announcements.shift();
    kRespond("(timer finished)", "timer service", next.text, now());
  }
  renderTimers();
  const open = k.windowOpenUntil - now();
  const armed = k.buttonUntil - now();
  $("k-status").textContent = [
    voice.wanted ? "Microphone on" : "Microphone off",
    voice.speaking ? "Chef is speaking" : null,
    armed > 0 ? "listening for your next words" : open > 0 ? `no wake word needed for ${Math.ceil(open)} s`
      : 'start with "Chef"',
  ].filter(Boolean).map(sentence).join(". ") + ".";
}

// -- Interview Coach -------------------------------------------------------------------------------

const c = { bank: null, plan: [], index: -1, state: "idle", analytics: null, parts: [], endTimer: null };

async function loadBank() {
  const res = await fetch(new URL("interview-coach/src/interview_coach/mcp_server/question_bank.json", ROOT));
  c.bank = await res.json();
}

function coachButtons() {
  const live = c.state === "asking" || c.state === "answering";
  $("c-start").disabled = live;
  $("c-done").disabled = c.state !== "answering";
  $("c-repeat").disabled = c.state !== "answering";
  $("c-end").disabled = !live;
  $("c-text").disabled = c.state !== "answering";
  $("c-status").textContent = {
    idle: "Not started.", asking: "Interviewer is speaking.",
    answering: voice.wanted ? "Your turn. Take your time." : "Your turn. Type your answer.",
    done: "Interview finished.",
  }[c.state];
}

async function coachSay(text) {
  const { start, end } = await voice.speak(text);
  c.analytics?.addAgentSpeech(start, end);
}

async function startInterview() {
  const family = $("c-family").value;
  const style = $("c-style").value;
  const count = Number($("c-count").value);
  c.plan = questionPlan(c.bank, family, $("c-level").value, style, count);
  c.analytics = new SpeechAnalytics();
  c.index = -1;
  c.state = "asking";
  $("c-report").replaceChildren();
  voice.handler = coachHandler;
  voice.start();
  coachButtons();
  const kind = style === "mixed" ? "" : ` ${style}`;
  await coachSay(`Hi, thanks for joining. This is a ${c.plan.length}-question${kind} mock interview. ` +
    "Take your time with each answer; silence is fine.");
  await askNext();
}

async function askNext() {
  clearTimeout(c.endTimer);
  if (c.state === "done") return;
  c.index += 1;
  if (c.index >= c.plan.length) return finishInterview();
  const q = c.plan[c.index];
  c.parts = [];
  c.state = "asking";
  coachButtons();
  $("c-question").textContent = `${c.index + 1} of ${c.plan.length} (${q.style}): ${q.text}`;
  $("c-answer").textContent = "";
  c.analytics.startQuestion(c.index, now());
  const lead = c.index === 0 ? "First question. " : c.index === c.plan.length - 1 ? "Last question. " : "Next question. ";
  await coachSay(lead + q.text);
  if (c.state !== "asking") return;
  c.state = "answering";
  coachButtons();
}

function addAnswer(seg) {
  c.analytics.addSegment(seg);
  c.parts.push(seg.text);
  $("c-answer").textContent = c.parts.join(" ");
}

const coachHandler = {
  final(seg) {
    if (c.state !== "answering" || seg.startedWhileSpeaking || voice.isEcho(seg)) return;
    addAnswer(seg);
    // Patient turn-taking: the answer is over only after a silence, longer if it trails off.
    clearTimeout(c.endTimer);
    c.endTimer = setTimeout(askNext, silenceBeforeTurnEnds(c.parts.join(" ")) * 1000);
  },
  interim(text) {
    if (c.state !== "answering") return;
    clearTimeout(c.endTimer); // still talking
    $("c-answer").textContent = [...c.parts, text].join(" ");
  },
};

async function finishInterview({ quiet = false } = {}) {
  clearTimeout(c.endTimer);
  c.state = "done";
  c.analytics.endQuestions();
  voice.stop();
  coachButtons();
  $("c-question").textContent = "";
  $("c-answer").textContent = "";
  renderReport();
  if (!quiet) await coachSay("That's the end of the interview. Thanks. Your report is below.");
}

function row(label, value) {
  const tr = el("tr");
  tr.append(el("th", label), el("td", value));
  return tr;
}

function renderReport() {
  const m = c.analytics.sessionMetrics();
  const out = [el("h3", "Report")];
  const summary = el("table");
  summary.append(
    row("Average pace", m.avgWpm ? `${m.avgWpm} words per minute` : "n/a (typed answers have no timing)"),
    row("Fillers per minute", String(m.fillersPerMin)),
    row("Share of the time you spoke", `${Math.round(m.talkRatio * 100)}%`),
    row("Average thinking time", m.avgThinkingTimeS == null ? "n/a" : `${m.avgThinkingTimeS} s`),
  );
  out.push(summary);
  m.answers.forEach((a, i) => {
    const q = c.plan[i];
    out.push(el("h4", `Question ${i + 1}: ${q.text}`));
    out.push(el("p", a.wordCount ? `You said: "${a.transcript}"` : "No answer given."));
    if (a.wordCount) {
      const t = el("table");
      const tics = Object.entries(a.verbalTics).map(([w, n]) => `"${w}" ×${n}`).join(", ") || "none";
      t.append(
        row("Words", `${a.wordCount} in ${a.durationS} s`),
        row("Pace", a.wpm ? `${a.wpm} wpm (${a.paceBand})` : "n/a"),
        row("Fillers (um, uh)", `${a.fillerCount} (${a.fillersPerMin} per minute)`),
        row("Verbal tics", tics),
        row("Longest pause", `${a.longestPauseS} s`),
        row("Thinking time before answering", a.thinkingTimeS == null ? "n/a" : `${a.thinkingTimeS} s`),
      );
      out.push(t);
    }
    out.push(el("p", "A strong answer covers:"));
    const ul = el("ul");
    ul.append(...q.good_answer_covers.map((x) => el("li", x)));
    out.push(ul);
  });
  out.push(el("p", "In the full app, Claude Opus 5.5 also scores each answer from 1 to 5 on structure, " +
    "specificity, impact, relevance and communication, quotes your own words as evidence, and writes a " +
    "three-point coaching plan."));
  $("c-report").replaceChildren(...out);
}

// -- page ------------------------------------------------------------------------------------------

function showTab(name) {
  voice.stop();
  voice.cancel();
  for (const tab of ["kitchen", "coach"]) {
    $(tab).hidden = tab !== name;
    $(`tab-${tab}`).setAttribute("aria-pressed", String(tab === name));
  }
  voice.handler = name === "kitchen" ? kitchenHandler : coachHandler;
  if (name !== "coach" && (c.state === "asking" || c.state === "answering")) finishInterview({ quiet: true });
}

function syncListenButton() {
  $("k-listen").textContent = voice.wanted ? "Stop listening" : "Start listening";
  $("k-listen").setAttribute("aria-pressed", String(voice.wanted));
}

async function main() {
  if (!Recognition) {
    notice("This browser has no speech recognition (Firefox doesn't support it), so type instead. " +
      "Chrome, Edge and Safari support voice.");
    $("k-listen").disabled = true;
    $("k-hey").disabled = true;
  }
  if (!tts) $("speak").checked = false;
  voice.onstate = syncListenButton;

  $("tab-kitchen").onclick = () => showTab("kitchen");
  $("tab-coach").onclick = () => showTab("coach");

  $("k-load").onclick = () => {
    const recipe = k.recipes.get($("k-recipe").value);
    k.announcements = [];
    const text = k.session.load(recipe);
    renderKitchen();
    kRespond(`(picked ${recipe.title} on screen)`, "screen tap", text, now());
  };
  $("k-listen").onclick = () => (voice.wanted ? voice.stop() : voice.start());
  $("k-hey").onclick = () => {
    k.buttonUntil = now() + BUTTON_TTL_S;
    voice.start();
  };
  $("k-form").onsubmit = (e) => {
    e.preventDefault();
    const text = $("k-text").value.trim();
    $("k-text").value = "";
    if (text) kitchenLine({ text, start: now(), end: now() }, true);
  };

  for (const level of LEVELS) $("c-level").append(Object.assign(el("option", level), { value: level }));
  $("c-level").value = "mid";
  $("c-start").onclick = startInterview;
  $("c-done").onclick = askNext;
  $("c-repeat").onclick = async () => {
    clearTimeout(c.endTimer);
    c.state = "asking";
    coachButtons();
    await coachSay(c.plan[c.index].text);
    c.state = "answering";
    coachButtons();
  };
  $("c-end").onclick = finishInterview;
  $("c-form").onsubmit = (e) => {
    e.preventDefault();
    const text = $("c-text").value.trim();
    $("c-text").value = "";
    if (!text || c.state !== "answering") return;
    addAnswer({ text, start: now(), end: now() });
    askNext();
  };

  showTab("kitchen");
  coachButtons();
  await Promise.all([loadRecipes(), loadBank()]);
  $("k-load").disabled = false;
  $("c-start").disabled = false;
  setInterval(kitchenTick, 250);
}

main().catch((err) => notice(`The demo failed to load: ${err.message}`));
