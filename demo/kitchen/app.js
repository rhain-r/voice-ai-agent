// Kitchen Companion demo page: browser speech in and out around the ported kitchen logic.

import {
  RecipeSession, TimerService, announcementText, decide, fastReply, isStopWord, parse, recipeFromBundle,
  sentence, speakable, toolRoute,
} from "./kitchen.js";
import { canListen, canSpeak, createVoice, now } from "../shared/voice.js";

const ROOT = new URL("../../", import.meta.url);
const RECIPE_IDS = ["fluffy-pancakes", "chicken-stir-fry", "chocolate-chip-cookies", "garlic-butter-pasta",
  "spinach-feta-omelette", "tomato-soup"];
const FOLLOWUP_S = 8; // attention.py: AttentionConfig.followup_window_s
const BUTTON_TTL_S = 10; // attention.py: BUTTON_TTL_S
const CONTINUATION_S = 3; // attention.py: CONTINUATION_S

const INTENT_NAMES = {
  next: "next step", prev: "go back", repeat: "repeat", goto: "go to step", stop: "stop",
  timer_start: "start a timer", timer_cancel: "cancel a timer", timer_query: "time left", yes: "yes",
  no: "no", ack: "acknowledge",
};
const ROUTE = {
  fast: (kind) => `Answered in code, no LLM: ${INTENT_NAMES[kind]}`,
  tool: (name) => `Tool: ${name}`,
  llm: "Needs Claude, not called in this demo",
  ignored: "Ignored: not addressed to Chef",
  wake: "Wake word only",
  screen: "Tapped on screen",
  timer: "Timer service",
};

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
const quoted = (text) => `“${text}”`;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const voice = createVoice({ onNotice: (text) => ($("notice").textContent = text), onState: renderDock });

const k = {
  recipes: new Map(),
  session: new RecipeSession(),
  timers: new TimerService(),
  windowOpenUntil: -Infinity,
  buttonUntil: -Infinity,
  announcements: [], // [{text, queuedAt}]
  timerKey: null,
};

// -- views of the pot: loading, error, picker, cooking ---------------------------------------------

function showView(name) {
  for (const view of ["loading", "error", "picker", "cooking"]) $(`pot-${view}`).hidden = view !== name;
}

async function loadRecipes() {
  const results = await Promise.all(RECIPE_IDS.map(async (id) => {
    const res = await fetch(new URL(`kitchen-companion/src/kitchen_companion/recipes/library/${id}.json`, ROOT));
    if (!res.ok) throw new Error(`${id}: HTTP ${res.status}`);
    return recipeFromBundle(await res.json());
  }));
  for (const recipe of results) k.recipes.set(recipe.id, recipe);
  $("recipes").replaceChildren(...results.map((recipe) => {
    const meta = [`${recipe.steps.length} steps`, `serves ${recipe.servings}`];
    if (recipe.totalTimeMin) meta.push(`${recipe.totalTimeMin} min`);
    const button = el("button", { type: "button", className: "recipe" },
      el("span", { className: "recipe-name", textContent: recipe.title }),
      el("span", { className: "recipe-meta", textContent: meta.join(", ") }));
    button.addEventListener("click", () => startRecipe(recipe));
    return el("li", {}, button);
  }));
}

function startRecipe(recipe) {
  k.announcements = [];
  const reply = k.session.load(recipe);
  showView("cooking");
  renderStep(true);
  renderSide();
  $("pot").focus();
  respond(`(picked ${recipe.title})`, ROUTE.screen, reply, now());
}

function renderStep(animate = false) {
  const s = k.session;
  if (!s.recipe) return;
  const total = s.recipe.steps.length;
  $("recipe-title").textContent = s.recipe.title;
  $("step-count").textContent = `Step ${s.index + 1} of ${total}`;
  const stepText = $("step-text");
  stepText.textContent = s.recipe.steps[s.index].text;
  if (animate && !reducedMotion.matches) {
    stepText.animate([{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }],
      { duration: 260, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
  }
  $("rail").replaceChildren(...s.recipe.steps.map((step, i) => {
    const button = el("button", { type: "button", textContent: String(i + 1) });
    button.setAttribute("aria-label", `Step ${i + 1}: ${step.text}`);
    if (i === s.index) button.setAttribute("aria-current", "step");
    button.addEventListener("click", () => {
      if (i === s.index) return;
      const reply = s.goto(i + 1);
      renderStep(true);
      respond(`(tapped step ${i + 1})`, ROUTE.screen, reply, now());
    });
    return el("li", { className: i < s.index ? "done" : "" }, button);
  }));
}

// -- side cards ------------------------------------------------------------------------------------

function renderSide() {
  const s = k.session;
  $("servings").textContent = s.recipe ? `(serves ${s.servings})` : "";
  $("ingredients").replaceChildren(...(s.recipe
    ? s.recipe.ingredients.map((i) => el("li", { textContent: s.ingredientText(i) }))
    : [el("li", { className: "empty", textContent: "Pick a recipe to see what goes in it." })]));
  $("ingredients").classList.toggle("is-empty", !s.recipe);
  renderTimers();
}

const clock = (seconds) => {
  const left = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
};

// Rebuild the list only when timers come or go, so a focused Cancel button keeps its focus.
function renderTimers() {
  const list = k.timers.list();
  const key = list.map((t) => `${t.id}:${t.state}`).join(",");
  if (key !== k.timerKey) {
    k.timerKey = key;
    $("timers").replaceChildren(...(list.length ? list.map((t) => {
      const due = t.state === "due";
      const action = el("button", { type: "button", className: "btn btn-quiet", textContent: due ? "Dismiss" : "Cancel" });
      action.setAttribute("aria-label", `${due ? "Dismiss" : "Cancel"} the ${t.label} timer`);
      action.addEventListener("click", () => { k.timers.cancel(t.id); renderTimers(); });
      const time = el("span", { className: "timer-clock", textContent: due ? "Done. Say “got it”." : clock(t.endsAt - now()) });
      time.dataset.id = t.id;
      return el("li", { className: due ? "timer due" : "timer" },
        el("span", { className: "timer-name", textContent: sentence(t.label) }), time, action);
    }) : [el("li", { className: "empty",
      textContent: "None running. Say “yes” when Chef offers one, or “Chef, set a timer for 5 minutes”." })]));
  }
  for (const t of list) {
    if (t.state !== "running") continue;
    const node = $("timers").querySelector(`[data-id="${t.id}"]`);
    if (node) node.textContent = clock(t.endsAt - now());
  }
}

// -- conversation log ------------------------------------------------------------------------------

function logTurn(you, route, chef, { ignored = false } = {}) {
  const ms = el("span", { className: "ms" });
  const turn = el("li", { className: ignored ? "turn ignored" : "turn" },
    el("p", { className: "you" }, el("span", { className: "who", textContent: "You" }), you),
    el("p", { className: "route-row" }, el("span", { className: "route", textContent: route }), ms));
  if (chef) turn.append(el("p", { className: "chef" }, el("span", { className: "who", textContent: "Chef" }), chef));
  $("log").querySelector(".empty-turn")?.remove();
  $("log").prepend(turn);
  return ms;
}

async function respond(heard, route, reply, heardAt) {
  const ms = logTurn(heard.startsWith("(") ? heard : quoted(heard), route, reply);
  await voice.speak(speakable(reply), (start) => {
    ms.textContent = `replied in ${Math.max(0, Math.round((start - heardAt) * 1000))} ms`;
  });
  // attention.py: Chef finishing a sentence opens the follow-up window.
  k.windowOpenUntil = now() + FOLLOWUP_S;
}

// -- one heard or typed line, through the attention gate and the router ---------------------------

function hear(seg, typed = false) {
  const t = now();
  if (!typed && voice.isEcho(seg)) return;
  if (!typed && seg.startedWhileSpeaking && !isStopWord(seg.text) && !/^\W*(?:hey |ok |okay )?chef\b/i.test(seg.text)) {
    return; // the microphone hearing Chef talk; only a stop word or the wake word cuts in
  }
  const d = decide(seg.text, {
    now: t, windowOpenUntil: k.windowOpenUntil, buttonArmed: t <= k.buttonUntil, botSpeaking: voice.speaking,
  });
  if (!d.engaged) {
    if (d.reason !== "empty") logTurn(quoted(seg.text), ROUTE.ignored, "", { ignored: true });
    return;
  }
  k.buttonUntil = -Infinity;
  if (!d.text) {
    respond(seg.text, ROUTE.wake, "Yes?", t);
    return;
  }
  // STT may split one utterance into several finals; keep listening for the rest of it.
  k.windowOpenUntil = Math.max(k.windowOpenUntil, t + CONTINUATION_S);

  const intent = parse(d.text);
  if (intent) {
    const wasSpeaking = voice.speaking;
    const before = k.session.index;
    const reply = fastReply(intent, k.session, k.timers);
    if (reply !== false) {
      // Kitchen noise doesn't cut Chef off: only a stop word or a command of 2+ words does.
      if (intent.kind === "stop" || (wasSpeaking && d.text.split(/\s+/).length >= 2)) voice.cancel();
      renderStep(k.session.index !== before);
      renderTimers();
      if (reply) respond(seg.text, ROUTE.fast(intent.kind), reply, t);
      else logTurn(quoted(seg.text), ROUTE.fast(intent.kind), "(stops talking)");
      return;
    }
  }
  const tool = toolRoute(d.text);
  if (tool) {
    let reply;
    if (tool.tool === "scale_recipe") {
      reply = k.session.scaleTo(tool.servings);
      renderSide();
    } else {
      const answer = k.session.ingredient(tool.name);
      reply = answer.found ? sentence(answer.text) + "." : answer.text;
    }
    respond(seg.text, ROUTE.tool(tool.tool), reply, t);
    return;
  }
  respond(seg.text, ROUTE.llm,
    "That one needs Claude, which this demo doesn't call. Try next, back, a timer, or how much of something.", t);
}

voice.handler = {
  final: (seg) => hear(seg),
  // A stop word cuts Chef off as soon as it's heard, before the transcript is final.
  interim: (text) => { if (voice.speaking && isStopWord(text)) voice.cancel(); },
};

// -- dock ------------------------------------------------------------------------------------------

function renderDock() {
  const listening = voice.wanted;
  $("mic").setAttribute("aria-pressed", String(listening));
  $("mic-label").textContent = listening ? "Stop listening" : "Start listening";
  const open = k.windowOpenUntil - now();
  const armed = k.buttonUntil - now();
  let gate;
  if (voice.speaking) gate = "Chef is talking. Say “stop” to cut in.";
  else if (armed > 0) gate = "Chef is listening for whatever you say next.";
  else if (open > 0) gate = `Go ahead, no “Chef” needed for ${Math.ceil(open)} s.`;
  else gate = "Start with “Chef”, as in “Chef, next step”.";
  $("attention-text").textContent = listening ? gate : `${gate} Microphone off, so type below.`;
  const fill = voice.speaking ? 0 : armed > 0 ? armed / BUTTON_TTL_S : Math.max(0, open) / FOLLOWUP_S;
  $("window-fill").style.transform = `scaleX(${Math.min(1, fill)})`;
}

function tick() {
  for (const [due, reminder] of k.timers.tick()) {
    const text = announcementText(due.map((t) => t.label), reminder ? null : k.session.nextStepText(), reminder);
    k.announcements.push({ text, queuedAt: now() });
  }
  // timers.py AnnouncementGate: wait until neither the cook nor Chef is talking (at most 8 s).
  const next = k.announcements[0];
  const quiet = !voice.speaking && now() - voice.lastHeardAt > 1;
  if (next && (quiet || now() - next.queuedAt > 8)) {
    k.announcements.shift();
    respond("(a timer finished)", ROUTE.timer, next.text, now());
  }
  renderTimers();
  renderDock();
}

// -- start -----------------------------------------------------------------------------------------

function wire() {
  $("mic").addEventListener("click", () => (voice.wanted ? voice.stop() : voice.start()));
  $("hey").addEventListener("click", () => {
    k.buttonUntil = now() + BUTTON_TTL_S;
    voice.start();
    renderDock();
  });
  $("say-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("say").value.trim();
    $("say").value = "";
    if (text) hear({ text, start: now(), end: now() }, true);
  });
  $("speak").addEventListener("change", () => {
    voice.speakEnabled = $("speak").checked;
    if (!voice.speakEnabled) voice.cancel();
  });
  $("change-recipe").addEventListener("click", () => {
    showView("picker");
    $("recipes").querySelector("button")?.focus();
  });
  $("reload").addEventListener("click", () => location.reload());

  if (!canListen) {
    $("mic").disabled = true;
    $("hey").disabled = true;
    $("notice").textContent = "This browser can't listen (Firefox has no speech recognition). " +
      "Type to Chef instead; Chrome, Edge and Safari can listen.";
  }
  if (!canSpeak) {
    $("speak").checked = false;
    $("speak").disabled = true;
    voice.speakEnabled = false;
  }
  $("log").append(el("li", { className: "empty-turn", textContent: "Nothing yet. Pick a recipe, then say “Chef, next step”." }));
}

async function main() {
  wire();
  renderSide();
  renderDock();
  try {
    await loadRecipes();
    showView("picker");
  } catch (err) {
    console.error(err);
    showView("error");
  }
  setInterval(tick, 250);
}

main();
