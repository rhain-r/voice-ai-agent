// Kitchen Companion logic, ported from kitchen-companion/src so it runs in the browser with no server.
// Each section names the Python module it mirrors; behaviour should match it line for line.

// -- fractions -----------------------------------------------------------------------------------

const gcd = (a, b) => {
  a = Math.abs(a);
  b = Math.abs(b);
  while (b) [a, b] = [b, a % b];
  return a || 1;
};

export class Frac {
  constructor(n, d = 1) {
    if (d < 0) [n, d] = [-n, -d];
    const g = gcd(n, d);
    this.n = n / g;
    this.d = d / g;
  }
  static of(x) {
    return x instanceof Frac ? x : new Frac(x);
  }
  // "2", "1/2", "1.5", ".5" or "1 1/2"
  static parse(text) {
    return text.trim().split(/\s+/).reduce((sum, part) => {
      if (part.includes("/")) {
        const [n, d] = part.split("/");
        return sum.add(new Frac(Number(n), Number(d)));
      }
      const [whole, dec = ""] = part.split(".");
      return sum.add(new Frac(Number((whole || "0") + dec), 10 ** dec.length));
    }, new Frac(0));
  }
  add(o) { o = Frac.of(o); return new Frac(this.n * o.d + o.n * this.d, this.d * o.d); }
  sub(o) { o = Frac.of(o); return new Frac(this.n * o.d - o.n * this.d, this.d * o.d); }
  mul(o) { o = Frac.of(o); return new Frac(this.n * o.n, this.d * o.d); }
  div(o) { o = Frac.of(o); return new Frac(this.n * o.d, this.d * o.n); }
  floor() { return Math.floor(this.n / this.d); }
  eq(o) { o = Frac.of(o); return this.n === o.n && this.d === o.d; }
  valueOf() { return this.n / this.d; }
  key() { return `${this.n}/${this.d}`; }
}

// -- recipes/units.py ----------------------------------------------------------------------------

export const COUNT_UNITS = new Set(["clove", "can", "pinch", "slice", "sprig", "bunch", "stick", "package"]);

const ALIASES = {
  tsp: ["tsp", "tsps", "tspn", "teaspoon", "teaspoons"],
  tbsp: ["tbsp", "tbsps", "tbs", "tbl", "tbls", "tablespoon", "tablespoons"],
  cup: ["cup", "cups"],
  ml: ["ml", "mls", "milliliter", "milliliters", "millilitre", "millilitres"],
  l: ["l", "liter", "liters", "litre", "litres"],
  floz: ["floz", "fl oz", "fl. oz", "fluid ounce", "fluid ounces"],
  g: ["g", "gr", "gram", "grams", "gramme", "grammes"],
  kg: ["kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"],
  oz: ["oz", "ounce", "ounces"],
  lb: ["lb", "lbs", "pound", "pounds"],
  clove: ["clove", "cloves"],
  can: ["can", "cans", "tin", "tins"],
  pinch: ["pinch", "pinches"],
  slice: ["slice", "slices"],
  sprig: ["sprig", "sprigs"],
  bunch: ["bunch", "bunches"],
  stick: ["stick", "sticks"],
  package: ["package", "packages", "pkg", "packet", "packets"],
};
const ALIAS_TO_UNIT = Object.fromEntries(
  Object.entries(ALIASES).flatMap(([unit, aliases]) => aliases.map((a) => [a, unit])),
);

const UNIT_NAMES = {
  tsp: ["teaspoon", "teaspoons"],
  tbsp: ["tablespoon", "tablespoons"],
  cup: ["cup", "cups"],
  ml: ["milliliter", "milliliters"],
  l: ["liter", "liters"],
  floz: ["fluid ounce", "fluid ounces"],
  g: ["gram", "grams"],
  kg: ["kilogram", "kilograms"],
  oz: ["ounce", "ounces"],
  lb: ["pound", "pounds"],
  pinch: ["pinch", "pinches"],
  bunch: ["bunch", "bunches"],
};

export function normalizeUnit(token) {
  const stripped = token.trim().replace(/\.+$/, "");
  if (stripped === "T") return "tbsp";
  if (stripped === "t") return "tsp";
  const key = stripped.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  return ALIAS_TO_UNIT[key] ?? null;
}

function stepFor(unit) {
  if (unit === "g" || unit === "ml" || unit === "oz" || COUNT_UNITS.has(unit)) return new Frac(1);
  if (unit == null) return new Frac(1, 2);
  return new Frac(1, 8);
}

// Round to a step a cook can measure. A positive amount never rounds down to zero.
export function roundKitchen(qty, unit) {
  const step = stepFor(unit);
  const x = Frac.of(qty).div(step);
  const rounded = Math.floor((2 * x.n + x.d) / (2 * x.d));
  if (rounded === 0 && qty > 0) return step;
  return step.mul(rounded);
}

const ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen " +
  "fifteen sixteen seventeen eighteen nineteen").split(" ");
const TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split(" ");

export function numberWords(n) {
  if (n < 0 || n > 9999 || !Number.isInteger(n)) return String(n);
  if (n < 20) return ONES[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? `-${ONES[n % 10]}` : "");
  if (n < 1000) return `${ONES[Math.floor(n / 100)]} hundred` + (n % 100 ? ` ${numberWords(n % 100)}` : "");
  return `${ONES[Math.floor(n / 1000)]} thousand` + (n % 1000 ? ` ${numberWords(n % 1000)}` : "");
}

// Spoken forms of a fractional part: [on its own with a unit, after "and", on its own without a unit].
const FRACTIONS = new Map([
  ["1/8", ["an eighth of {a} {one}", "an eighth", "an eighth"]],
  ["1/4", ["a quarter {one}", "a quarter", "a quarter"]],
  ["1/3", ["a third of {a} {one}", "a third", "a third"]],
  ["3/8", ["three eighths of {a} {one}", "three eighths", "three eighths"]],
  ["1/2", ["half {a} {one}", "a half", "half"]],
  ["5/8", ["five eighths of {a} {one}", "five eighths", "five eighths"]],
  ["2/3", ["two thirds of {a} {one}", "two thirds", "two thirds"]],
  ["3/4", ["three quarters of {a} {one}", "three quarters", "three quarters"]],
  ["7/8", ["seven eighths of {a} {one}", "seven eighths", "seven eighths"]],
]);

function unitWords(unit) {
  if (unit == null) return ["", ""];
  if (UNIT_NAMES[unit]) return UNIT_NAMES[unit];
  return [unit, unit.endsWith("s") ? unit : unit + "s"];
}

// Snap a fractional part (0 < frac < 1) to the nearest speakable fraction, carrying into wholes.
function nearestFraction(frac) {
  const options = [new Frac(0), ...[...FRACTIONS.keys()].map(Frac.parse), new Frac(1)];
  let best = options[0];
  for (const f of options) if (Math.abs(f - frac) < Math.abs(best - frac)) best = f;
  return best.eq(1) ? [1, new Frac(0)] : [0, best];
}

export function speakQuantity(qty, unit) {
  qty = Frac.of(qty);
  let whole = qty.floor();
  let frac = qty.sub(whole);
  if (frac.n) {
    const [carry, snapped] = nearestFraction(frac);
    whole += carry;
    frac = snapped;
  }
  const [one, many] = unitWords(unit);
  if (!frac.n) return `${numberWords(whole)} ${whole === 1 ? one : many}`.trim();
  const [alone, afterAnd, bare] = FRACTIONS.get(frac.key());
  if (whole === 0) {
    if (!one) return bare;
    return alone.replace("{a}", "aeiou".includes(one[0]) ? "an" : "a").replace("{one}", one);
  }
  return `${numberWords(whole)} and ${afterAnd} ${many}`.trim();
}

// -- recipes/ingredients.py ----------------------------------------------------------------------

const UNICODE_FRACTIONS = {
  "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅖": "2/5", "⅗": "3/5",
  "⅘": "4/5", "⅙": "1/6", "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
};
const ING_UNICODE_RE = new RegExp(`(\\d?)\\s*([${Object.keys(UNICODE_FRACTIONS).join("")}])`, "g");
const ING_NUM = String.raw`(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|\.\d+)`;
const LEAD = new RegExp(String.raw`^\s*(?<qty>${ING_NUM})(?:\s*(?:-|to)\s*(?<max>${ING_NUM}))?\s*`, "i");
const ARTICLE = /^\s*an?\s+/i;
const PAREN = /\(\s*([^)]*?)\s*\)/;
const PAREN_ALL = /\(\s*([^)]*?)\s*\)/g;
const TWO_WORD_UNIT = /^(fl\.?\s*oz\.?|fluid\s+ounces?)(?=\s|$)/i;
const WORD = /^([A-Za-z]+\.?)(?=\s|$|,)/;
const OF = /^of\s+/i;

function expandUnicode(line) {
  return line
    .replace(/⁄/g, "/")
    .replace(ING_UNICODE_RE, (_, whole, f) => (whole ? `${whole} ${UNICODE_FRACTIONS[f]}` : UNICODE_FRACTIONS[f]))
    .replace(/–/g, "-")
    .replace(/—/g, "-");
}

function takeUnit(rest) {
  let m = TWO_WORD_UNIT.exec(rest);
  if (m) return ["floz", rest.slice(m[0].length).trimStart()];
  m = WORD.exec(rest);
  if (m) {
    const unit = normalizeUnit(m[1]);
    if (unit) return [unit, rest.slice(m[0].length).trimStart()];
  }
  return [null, rest];
}

// Never throws: a line without a leading quantity keeps the whole line as its name.
export function parseIngredient(line) {
  const unparsed = { qty: null, qtyMax: null, unit: null, name: line.trim(), note: null, raw: line };
  const text = expandUnicode(line);
  const notes = [];
  let qty, qtyMax = null, rest;

  const m = LEAD.exec(text);
  if (m) {
    qty = Frac.parse(m.groups.qty);
    qtyMax = m.groups.max ? Frac.parse(m.groups.max) : null;
    rest = text.slice(m[0].length);
  } else {
    const article = ARTICLE.exec(text);
    if (!article) return unparsed;
    const [unit] = takeUnit(text.slice(article[0].length));
    if (unit == null) return unparsed;
    qty = new Frac(1);
    rest = text.slice(article[0].length);
  }

  const paren = PAREN.exec(rest);
  if (paren && paren.index === 0) {
    notes.push(paren[1]);
    rest = rest.slice(paren[0].length).trimStart();
  }

  let unit;
  [unit, rest] = takeUnit(rest);
  rest = rest.replace(OF, "");

  for (const inner of rest.matchAll(PAREN_ALL)) notes.push(inner[1]);
  rest = rest.replace(PAREN_ALL, " ").split(/\s+/).filter(Boolean).join(" ");

  const comma = rest.indexOf(",");
  const name = (comma < 0 ? rest : rest.slice(0, comma)).trim();
  const trailing = comma < 0 ? "" : rest.slice(comma + 1).trim();
  if (trailing) notes.push(trailing);
  if (!name) return unparsed;
  return { qty, qtyMax, unit, name, note: notes.filter(Boolean).join(", ") || null, raw: line };
}

// recipes/library.py: bundled JSON keeps ingredients as plain lines, parsed the same way imported ones are.
export function recipeFromBundle(data) {
  return {
    id: data.id,
    title: data.title,
    servings: data.servings ?? 4,
    totalTimeMin: data.total_time_min ?? null,
    ingredients: data.ingredients.map(parseIngredient),
    steps: data.steps.map((s, i) => ({ index: i, text: s.text, timerMinutes: s.timer_minutes ?? null })),
  };
}

// -- recipes/state.py ----------------------------------------------------------------------------

const NO_RECIPE = "No recipe loaded yet. Pick one on the screen or ask me to find one.";
const NO_STEPS = "This recipe has no steps.";
const LAST_STEP = "That was the last step. Enjoy!";
const FIRST_STEP = "We're at the first step. ";

const COOKING_VERBS = new Set([
  "boil", "simmer", "bake", "roast", "fry", "saute", "cook", "rest", "chill", "marinate",
  "steam", "toast", "sear", "proof", "rise", "knead", "whisk",
]);

const words = (text) => text.toLowerCase().replace(/é/g, "e").match(/[a-z0-9]+/g) ?? [];

function singular(token) {
  if (token.length <= 3) return token;
  if (token.endsWith("ies")) return token.slice(0, -3) + "y";
  if (token.endsWith("es") && /(?:s|x|z|ch|sh|o)$/.test(token.slice(0, -2))) return token.slice(0, -2);
  if (token.endsWith("s") && !token.endsWith("ss")) return token.slice(0, -1);
  return token;
}

// Lowercased, punctuation-free, singularized word set used for fuzzy ingredient matching.
export const tokens = (text) => new Set(words(text).map(singular));

const article = (word) => ("aeiou".includes(word[0]) ? "an" : "a");
const isSubset = (a, b) => [...a].every((x) => b.has(x));
const setEq = (a, b) => a.size === b.size && isSubset(a, b);

export class RecipeSession {
  constructor() {
    this.recipe = null;
    this.index = 0;
    this.scale = new Frac(1);
    this.pendingTimerOffer = null;
  }

  load(recipe) {
    this.recipe = recipe;
    this.index = 0;
    this.scale = new Frac(1);
    this.pendingTimerOffer = null;
    const n = recipe.steps.length;
    if (n === 0) return `Okay, ${recipe.title}. ${NO_STEPS}`;
    const count = n === 1 ? "One step" : `${sentence(numberWords(n))} steps`;
    return `Okay, ${recipe.title}. ${count}. ` + this.current();
  }

  guard() {
    if (this.recipe == null) return NO_RECIPE;
    if (!this.recipe.steps.length) {
      this.pendingTimerOffer = null;
      return NO_STEPS;
    }
    return null;
  }

  current() {
    const msg = this.guard();
    if (msg != null) return msg;
    const step = this.recipe.steps[this.index];
    let say = `Step ${numberWords(this.index + 1)}: ${step.text}`;
    if (step.timerMinutes) {
      const w = numberWords(step.timerMinutes);
      say += ` Want ${article(w)} ${w}-minute timer?`;
      this.pendingTimerOffer = step.timerMinutes;
    } else {
      this.pendingTimerOffer = null;
    }
    return say;
  }

  next() {
    const msg = this.guard();
    if (msg != null) return msg;
    if (this.index >= this.recipe.steps.length - 1) return LAST_STEP;
    this.index += 1;
    return this.current();
  }

  prev() {
    const msg = this.guard();
    if (msg != null) return msg;
    if (this.index === 0) return FIRST_STEP + this.current();
    this.index -= 1;
    return this.current();
  }

  goto(n) {
    const msg = this.guard();
    if (msg != null) return msg;
    const total = this.recipe.steps.length;
    if (!(n >= 1 && n <= total)) return `This recipe has ${numberWords(total)} steps.`;
    this.index = n - 1;
    return this.current();
  }

  repeat() {
    return this.current();
  }

  get servings() {
    return this.recipe ? Math.round(this.scale.mul(this.recipe.servings)) : null;
  }

  scaleTo(servings) {
    if (this.recipe == null) return NO_RECIPE;
    if (servings < 1) return "I can only scale to one serving or more.";
    this.scale = new Frac(servings, this.recipe.servings || 1);
    return `Scaled to ${numberWords(servings)} servings.`;
  }

  // The ingredient line as spoken, with its quantity scaled and rounded for the kitchen.
  ingredientText(ing) {
    if (ing.qty == null) return ing.raw.trim();
    const low = roundKitchen(ing.qty.mul(this.scale), ing.unit);
    let amount;
    if (ing.qtyMax != null) {
      const high = roundKitchen(ing.qtyMax.mul(this.scale), ing.unit);
      amount = `${speakQuantity(low, null)} to ${speakQuantity(high, ing.unit)}`;
    } else {
      amount = speakQuantity(low, ing.unit);
    }
    const text = `${amount} ${ing.name}`;
    return ing.note ? `${text}, ${ing.note}` : text;
  }

  ingredient(name) {
    if (this.recipe == null) return { found: false, text: NO_RECIPE };
    const query = tokens(name);
    if (!query.size) return { found: false, text: "Which ingredient?" };
    const nameTokens = (ing) => {
      const t = tokens(ing.name);
      if (COUNT_UNITS.has(ing.unit)) t.add(ing.unit);
      return t;
    };
    let matches = this.recipe.ingredients.filter((ing) => isSubset(query, nameTokens(ing)));
    const exact = matches.filter((ing) => setEq(tokens(ing.name), query));
    if (matches.length > 1 && exact.length === 1) matches = exact;
    if (!matches.length) return { found: false, text: `I don't see ${name} in this recipe.` };
    if (matches.length === 1) return { found: true, text: this.ingredientText(matches[0]) };
    const candidates = matches.map((ing) => (ing.note ? `the ${ing.name}, ${ing.note}` : `the ${ing.name}`));
    return { found: false, text: "Do you mean " + candidates.join(" or ") + "?" };
  }

  timerLabel() {
    if (this.recipe == null || !this.recipe.steps.length) return null;
    for (const word of words(this.recipe.steps[this.index].text)) {
      if (COOKING_VERBS.has(word)) return word;
    }
    return `step ${this.index + 1}`;
  }

  nextStepText() {
    if (this.recipe == null || this.index + 1 >= this.recipe.steps.length) return null;
    return this.recipe.steps[this.index + 1].text;
  }
}

// -- timers.py -----------------------------------------------------------------------------------

export class TimerService {
  constructor({ clock = () => performance.now() / 1000, reminderInterval = 60, maxReminders = 3 } = {}) {
    this.clock = clock;
    this.reminderInterval = reminderInterval;
    this.maxReminders = maxReminders;
    this.timers = new Map();
    this.ids = 1;
  }

  // Timers that are still running or ringing, in start order.
  list() {
    return [...this.timers.values()].filter((t) => t.state === "running" || t.state === "due");
  }

  start(minutes, label = null) {
    const taken = new Set(this.list().map((t) => t.label));
    if (label == null) {
      let n = 1;
      while (taken.has(`timer ${n}`)) n += 1;
      label = `timer ${n}`;
    } else {
      const base = label.trim();
      let n = 2;
      label = base;
      while (taken.has(label)) label = `${base} ${n++}`;
    }
    const timer = { id: `t${this.ids++}`, label, minutes, endsAt: this.clock() + minutes * 60,
      state: "running", reminders: 0, lastAnnounced: null };
    this.timers.set(timer.id, timer);
    return timer;
  }

  matching(label) {
    const active = this.list();
    if (label == null) return active;
    const needle = label.trim().toLowerCase();
    return active.filter((t) => t.label.toLowerCase().includes(needle) || t.id === label);
  }

  cancel(label = null) {
    const matches = this.matching(label);
    if (matches.length > 1) return { cancelled: [], ambiguous: matches.map((t) => t.label) };
    for (const t of matches) {
      t.state = "cancelled";
      this.timers.delete(t.id);
    }
    return { cancelled: matches, ambiguous: [] };
  }

  remaining(label = null) {
    const now = this.clock();
    return this.matching(label).filter((t) => t.state === "running").map((t) => [t, Math.max(0, t.endsAt - now)]);
  }

  acknowledge() {
    const due = [...this.timers.values()].filter((t) => t.state === "due");
    for (const t of due) {
      t.state = "acknowledged";
      this.timers.delete(t.id);
    }
    return due;
  }

  // Returns [timers, isReminder] pairs that should be announced now.
  tick() {
    const now = this.clock();
    const out = [];
    const newlyDue = this.list().filter((t) => t.state === "running" && t.endsAt <= now);
    for (const t of newlyDue) {
      t.state = "due";
      t.lastAnnounced = now;
    }
    if (newlyDue.length) out.push([newlyDue, false]);
    const reminders = [...this.timers.values()].filter((t) => t.state === "due" && !newlyDue.includes(t) &&
      t.reminders < this.maxReminders && now - (t.lastAnnounced ?? now) >= this.reminderInterval);
    for (const t of reminders) {
      t.reminders += 1;
      t.lastAnnounced = now;
    }
    if (reminders.length) out.push([reminders, true]);
    return out;
  }
}

// 480 -> "eight minutes", 90 -> "one minute and thirty seconds". Rounded to the second.
export function speakDuration(seconds) {
  const total = Math.round(seconds);
  if (total <= 0) return "less than a second";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const parts = [[hours, "hour"], [minutes, "minute"], [secs, "second"]]
    .filter(([n]) => n)
    .map(([n, unit]) => `${numberWords(n)} ${n === 1 ? unit : unit + "s"}`);
  return parts.length <= 2 ? parts.join(" and ") : `${parts[0]}, ${parts[1]} and ${parts[2]}`;
}

const timerPhrase = (label) => (label.toLowerCase().startsWith("timer") ? label : `${label} timer`);
const theTimer = (label) => {
  const phrase = timerPhrase(label);
  return phrase.toLowerCase().startsWith("timer") ? phrase : `the ${phrase}`;
};
export const sentence = (text) => text.slice(0, 1).toUpperCase() + text.slice(1);

export const startedReply = (timer) =>
  sentence(`${timerPhrase(timer.label)} set for ${speakDuration(timer.minutes * 60)}.`);

export function cancelReply(service, label) {
  const result = service.cancel(label);
  if (result.ambiguous.length) return ["Which timer, " + result.ambiguous.join(" or ") + "?", false];
  if (!result.cancelled.length) {
    if (label && service.list().length) return [`I don't see ${theTimer(label)}.`, false];
    return ["There's no timer running.", false];
  }
  return [`Cancelled ${theTimer(result.cancelled[0].label)}.`, true];
}

export function remainingReply(service, label = null) {
  const left = service.remaining(label);
  if (!left.length) {
    if (label && service.list().length) return `I don't see ${theTimer(label)}.`;
    return "No timers running.";
  }
  return left.map(([t, secs]) => sentence(`${theTimer(t.label)} has ${speakDuration(secs)} left.`)).join(" ");
}

const joinAnd = (items) => (items.length === 1 ? items[0] : items.slice(0, -1).join(", ") + " and " + items.at(-1));

export function announcementText(labels, nextStep, reminder) {
  const names = labels.some((l) => l.toLowerCase().startsWith("timer"))
    ? joinAnd(labels.map(timerPhrase))
    : joinAnd(labels) + (labels.length === 1 ? " timer" : " timers");
  if (reminder) return `Reminder: your ${names} went off.`;
  let text = `Your ${names} ${labels.length === 1 ? "is" : "are"} done.`;
  if (nextStep) text += ` Next up: ${nextStep}`;
  return text;
}

// -- pipeline/fast_path.py -----------------------------------------------------------------------

const POLITE = new Set(["please", "okay", "ok", "alright", "now", "chef"]);
const PUNCT = /[^\w\s.]|(?<!\d)\.|\.(?!\d)/g;

const normalize = (text) =>
  text.toLowerCase().replace(/’/g, "'").replace(/'/g, "").replace(PUNCT, " ").split(/\s+/).filter(Boolean).join(" ");

function stripPolite(text) {
  const w = text.split(" ").filter(Boolean);
  while (w.length && POLITE.has(w[0])) w.shift();
  while (w.length && POLITE.has(w.at(-1))) w.pop();
  return w.join(" ");
}

const FP_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
  "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const FP_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
const ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"];

export const WORD_VALUES = Object.fromEntries(FP_ONES.map((w, i) => [w, i + 1]));
FP_TENS.forEach((tens, i) => {
  WORD_VALUES[tens] = 20 + 10 * i;
  FP_ONES.slice(0, 9).forEach((one, j) => (WORD_VALUES[`${tens} ${one}`] = 20 + 10 * i + j + 1));
});

const NUMBER_WORD = Object.keys(WORD_VALUES).sort((a, b) => b.length - a.length).join("|");
const FP_NUM = String.raw`(?:\d+(?:\.\d+)?|${NUMBER_WORD}|an|a)`;
const FP_UNIT = String.raw`(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)`;
const PART_SRC = String.raw`\b(?:half (?:an|a) (?<half_unit>hour|minute)` +
  String.raw`|(?<num>${FP_NUM})(?<pre_half> and a half)? (?<unit>${FP_UNIT})(?<post_half> and a half)?)\b`;
const PART = new RegExp(PART_SRC);
const PART_AT = new RegExp(PART_SRC, "y");
const JOINER_AT = /\s+(?:and\s+)?/y;

function numberOf(token) {
  if (token === "a" || token === "an") return 1;
  if (token in WORD_VALUES) return WORD_VALUES[token];
  const v = Number(token);
  return Number.isNaN(v) ? null : v;
}

function partMinutes(m) {
  const g = m.groups;
  if (g.half_unit) return g.half_unit === "hour" ? 30 : 0.5;
  let value = numberOf(g.num) || 0;
  if (g.pre_half || g.post_half) value += 0.5;
  if (g.unit.startsWith("h")) return value * 60;
  if (g.unit.startsWith("s")) return value / 60;
  return value;
}

// Total minutes of the first run of duration parts ("1 hour 15 minutes"), with its span.
function findDuration(text) {
  const m = PART.exec(text);
  if (!m) return null;
  let total = partMinutes(m);
  const start = m.index;
  let end = m.index + m[0].length;
  for (;;) {
    JOINER_AT.lastIndex = end;
    const joiner = JOINER_AT.exec(text);
    if (!joiner) break;
    PART_AT.lastIndex = JOINER_AT.lastIndex;
    const nxt = PART_AT.exec(text);
    if (!nxt) break;
    total += partMinutes(nxt);
    end = PART_AT.lastIndex;
  }
  return [total, start, end];
}

const PHRASES = {
  next: ["next", "next step", "next one", "whats next", "what is next", "whats the next step", "done",
    "im done", "all done", "finished", "im finished", "go on", "continue", "keep going", "move on",
    "ready", "im ready", "go ahead and continue", "lets keep going"],
  prev: ["back", "go back", "previous", "previous step", "go back a step", "go back one step",
    "step back", "back one", "back a step", "one step back", "go back one"],
  repeat: ["repeat", "repeat that", "say that again", "say again", "what was that", "come again",
    "again", "pardon", "pardon me", "sorry what", "what did you say", "repeat the step",
    "repeat step", "read that again", "one more time", "huh"],
  stop: ["stop", "quiet", "be quiet", "pause", "wait", "hold on", "hang on", "shush", "shh", "enough",
    "stop talking", "thats enough", "one moment", "hold it"],
  yes: ["yes", "yeah", "yep", "yup", "sure", "sure thing", "do it", "please do", "go for it",
    "sounds good", "yes do it", "yes start it", "start it", "absolutely", "definitely"],
  no: ["no", "nope", "nah", "no thanks", "no thank you", "not now", "not yet", "skip it", "no need",
    "dont", "maybe later"],
  ack: ["got it", "thanks", "thank you", "okay", "ok", "alright", "ok got it", "okay got it",
    "understood", "roger", "cool", "great", "perfect", "will do", "on it", "heard"],
};
const PHRASE_SETS = Object.entries(PHRASES).map(([kind, list]) => [kind, new Set(list)]);
const ACK = new Set(PHRASES.ack);

const STEP_NUMBER = `(\\d+|${NUMBER_WORD})`;
const GOTO = new RegExp(
  `^(?:(?:go|jump|skip|move|take me|back)(?: back)? to )?(?:the )?step (?:number )?${STEP_NUMBER}$`);
const GOTO_ORDINAL = new RegExp(
  `^(?:(?:go|jump|skip|move|take me|back)(?: back)? to )?(?:the )?(${ORDINALS.join("|")}) step$`);

const TIMER_WORD = /\btimers?\b/;
// The verb has to come before "timer": "when does the timer end" is a question, not a command.
const CANCEL_WORD = /\b(?:cancel|stop|delete|remove|clear|kill|turn off|end|reset|dismiss)\b.*\btimers?\b/;
// Questions and remarks about a timer are the LLM's to answer ("how do I reset the timer").
const QUESTION_START = /^(?:how|what|whats|when|why|where|which|who|does|do|did|is|should)\b/;
const NOT_A_LABEL = new Set(["left", "says", "said", "remaining", "until", "still", "already", "is", "was", "went", "ago"]);
const QUERY_START = /^(?:how long|how much time|how many minutes|whats left|time left|time check)\b/;
const QUERY_TARGET = /\b(?:left|remaining|until|till|til|to go|timers?)\b|^(?:how long|how much time) (?:is )?on\b/;

const START_FILLER = new Set(["set", "start", "a", "an", "the", "me", "my", "timer", "for", "please", "can", "you",
  "put", "on", "of", "make", "up", "new", "another", "quick", "called", "named", "labeled", "and", "give", "get",
  "add", "us", "i", "need", "want", "to", "go", "could", "would"]);
const CANCEL_FILLER = new Set(["cancel", "stop", "delete", "remove", "clear", "kill", "turn", "off", "end", "reset",
  "dismiss", "the", "my", "a", "timer", "timers", "please", "for", "that", "this", "on", "can", "you", "could"]);
const QUERY_FILLER = new Set(["how", "long", "much", "time", "is", "left", "on", "the", "my", "timer", "timers",
  "until", "till", "til", "to", "go", "remaining", "whats", "what", "are", "there", "do", "i", "have", "many",
  "minutes", "done", "ready", "check", "does", "it", "of", "for", "a", "any", "be", "will", "s"]);
const MAX_LABEL_WORDS = 3;

// Leftover words after the command words: [ok, label]. Too many leftovers, or (for a command)
// words that describe a timer rather than name one ("the timer says 5 minutes left"), mean no.
function label(text, filler, command = true) {
  const w = text.split(" ").filter((x) => x && !filler.has(x));
  if (w.length > MAX_LABEL_WORDS || (command && w.some((x) => NOT_A_LABEL.has(x)))) return [false, null];
  return [true, w.join(" ") || null];
}

function timerIntent(text) {
  if (QUERY_START.test(text) && QUERY_TARGET.test(text)) {
    const [ok, lbl] = label(text, QUERY_FILLER, false);
    return ok ? { kind: "timer_query", label: lbl } : null;
  }
  if (!TIMER_WORD.test(text) || QUESTION_START.test(text)) return null;
  if (CANCEL_WORD.test(text)) {
    const [ok, lbl] = label(text, CANCEL_FILLER);
    return ok ? { kind: "timer_cancel", label: lbl } : null;
  }
  const found = findDuration(text);
  if (!found || found[0] <= 0) return null;
  const [minutes, start, end] = found;
  const [ok, lbl] = label(text.slice(0, start) + " " + text.slice(end), START_FILLER);
  return ok ? { kind: "timer_start", minutes, label: lbl } : null;
}

// A short kitchen command answered from code, or null for "hand it to the LLM".
export function parse(text) {
  const raw = normalize(text);
  if (!raw) return null;
  if (ACK.has(raw)) return { kind: "ack" };
  const t = stripPolite(raw);
  if (!t) return null;
  for (const [kind, phrases] of PHRASE_SETS) {
    if (phrases.has(raw) || phrases.has(t)) return { kind }; // "not now" is a phrase even though "now" is filler
  }
  let m = GOTO.exec(t);
  if (m) return { kind: "goto", n: /^\d+$/.test(m[1]) ? Number(m[1]) : WORD_VALUES[m[1]] };
  m = GOTO_ORDINAL.exec(t);
  if (m) return { kind: "goto", n: ORDINALS.indexOf(m[1]) + 1 };
  return timerIntent(t);
}

// FastPathRouter._reply: the spoken reply, null for a silent command, or false when it doesn't apply now.
export function fastReply(intent, recipe, timers) {
  const { kind } = intent;
  if (kind === "next") return recipe.next();
  if (kind === "prev") return recipe.prev();
  if (kind === "repeat") return recipe.repeat();
  if (kind === "goto") return recipe.goto(intent.n || 1);
  if (kind === "stop") {
    timers.acknowledge();
    return null;
  }
  if (kind === "timer_start") return startedReply(timers.start(intent.minutes || 0, intent.label || recipe.timerLabel()));
  if (kind === "timer_cancel") return cancelReply(timers, intent.label)[0];
  if (kind === "timer_query") return remainingReply(timers, intent.label);
  if (kind === "yes") {
    if (recipe.pendingTimerOffer == null) return false;
    const minutes = recipe.pendingTimerOffer;
    recipe.pendingTimerOffer = null;
    return startedReply(timers.start(minutes, recipe.timerLabel()));
  }
  if (kind === "no") {
    if (recipe.pendingTimerOffer == null) return false;
    recipe.pendingTimerOffer = null;
    return "Okay.";
  }
  if (kind === "ack") return timers.acknowledge().length ? "Got it." : false;
  return false;
}

// -- pipeline/attention.py -----------------------------------------------------------------------

export const STOP_WORDS = ["stop", "wait", "quiet", "be quiet", "hold on", "pause"];
const STOP_RE = new RegExp(`^\\s*(?:${STOP_WORDS.join("|")})(?:[\\s,]+please)?[\\s.!]*$`, "i");

function wakePattern(wakePhrase) {
  const wake = wakePhrase.split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  return new RegExp(`^\\s*(?:(?:hey|hi|ok|okay|yo)[\\s,]+)?(?:${wake})(?!['’]s)\\b[\\s,.!?]*`, "i");
}

// Is this line addressed to the bot? Returns {engaged, text, reason}.
export function decide(text, { now, windowOpenUntil, buttonArmed, botSpeaking, wakePhrase = "chef" }) {
  if (!text || !text.trim()) return { engaged: false, text, reason: "empty" };
  const m = wakePattern(wakePhrase).exec(text);
  if (m) return { engaged: true, text: text.slice(m[0].length).trim(), reason: "wake" };
  if (buttonArmed) return { engaged: true, text, reason: "button" };
  if (now <= windowOpenUntil) return { engaged: true, text, reason: "followup" };
  if (botSpeaking && STOP_RE.test(text)) return { engaged: true, text, reason: "stop_word" };
  return { engaged: false, text, reason: "not_addressed" };
}

export const isStopWord = (text) => STOP_RE.test(text);

// -- pipeline/speakable.py: "1 1/2 cups" -> "one and a half cups" right before text-to-speech ----

const SPK_UNICODE = { "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅛": "1/8", "⅜": "3/8",
  "⅝": "5/8", "⅞": "7/8" };
const SPK_UNICODE_RE = new RegExp(`(\\d?)\\s*([${Object.keys(SPK_UNICODE).join("")}])`, "g");
const TIME_UNITS = {
  min: ["minute", "minutes"], mins: ["minute", "minutes"], minute: ["minute", "minutes"],
  minutes: ["minute", "minutes"], hr: ["hour", "hours"], hrs: ["hour", "hours"],
  hour: ["hour", "hours"], hours: ["hour", "hours"], sec: ["second", "seconds"],
  secs: ["second", "seconds"], second: ["second", "seconds"], seconds: ["second", "seconds"],
};
// Abbreviations spoken in full even without a number in front.
const BARE_ABBREVIATIONS = {
  tbsp: "tablespoons", tbsps: "tablespoons", tsp: "teaspoons", tsps: "teaspoons",
  oz: "ounces", lb: "pounds", lbs: "pounds", ml: "milliliters", min: "minutes",
  mins: "minutes", hr: "hours", hrs: "hours", sec: "seconds", secs: "seconds",
};
const SPK_NUM = String.raw`(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)`;
const MARKDOWN = [
  [/\[([^\]]+)\]\([^)]*\)/g, "$1"],
  [/(\*\*|__)(.+?)\1/g, "$2"],
  [/(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, "$1"],
  [/`([^`]*)`/g, "$1"],
  [/^\s*#{1,6}\s+/gm, ""],
  [/^\s*(?:[-*•]|\d+\.)\s+/gm, ""],
];
const THOUSANDS = /(?<=\d),(?=\d{3}(?!\d))/g;
const TEMP = new RegExp(String.raw`(?<![\w/])(${SPK_NUM})\s*°\s*([FC])?\b`, "g");
const RANGE = new RegExp(String.raw`(?<![\w/])(${SPK_NUM})\s*[-–—]\s*(${SPK_NUM})(?:\s*([A-Za-z]+)\b\.?)?`, "g");
const QTY_UNIT = new RegExp(String.raw`(?<![\w/])(${SPK_NUM})\s*([A-Za-z]+)\b(\.?)`, "g");
const BARE = new RegExp(String.raw`\b(${Object.keys(BARE_ABBREVIATIONS).join("|")})\b`, "gi");
const NUMBER = new RegExp(String.raw`(?<![\w/.])(${SPK_NUM})(?![\w/]|\.\d)`, "g");

function quantityWithUnit(qty, word) {
  const time = TIME_UNITS[word.toLowerCase()];
  if (time) return speakQuantity(qty, null) + " " + (qty.eq(1) ? time[0] : time[1]);
  const unit = normalizeUnit(word);
  return unit == null ? null : speakQuantity(qty, unit);
}

export function speakable(text) {
  for (const [pattern, repl] of MARKDOWN) text = text.replace(pattern, repl);
  text = text.replace(THOUSANDS, "");
  text = text.replace(SPK_UNICODE_RE, (_, whole, f) => `${whole} ${SPK_UNICODE[f]}`.trim());
  text = text.replace(TEMP, (_, num, scale) => {
    const suffix = { F: " Fahrenheit", C: " Celsius" }[scale ?? ""] ?? "";
    return `${speakQuantity(Frac.parse(num), null)} degrees${suffix}`;
  });
  text = text.replace(RANGE, (_, lo, hi, word) => {
    const low = Frac.parse(lo);
    const high = Frac.parse(hi);
    if (word) {
      const spokenHigh = quantityWithUnit(high, word);
      if (spokenHigh != null) return `${speakQuantity(low, null)} to ${spokenHigh}`;
      return `${speakQuantity(low, null)} to ${speakQuantity(high, null)} ${word}`;
    }
    return `${speakQuantity(low, null)} to ${speakQuantity(high, null)}`;
  });
  text = text.replace(QTY_UNIT, (all, num, word, dot) => {
    const spoken = quantityWithUnit(Frac.parse(num), word);
    return spoken == null ? all : spoken + dot;
  });
  text = text.replace(BARE, (w) => BARE_ABBREVIATIONS[w.toLowerCase()]);
  text = text.replace(NUMBER, (_, num) => {
    const value = Frac.parse(num);
    return value.d === 1 ? numberWords(value.n) : speakQuantity(value, null);
  });
  return text;
}

// -- demo-only routing for the two LLM tools the demo can run without Claude ----------------------
// In the full app Claude Haiku decides to call get_ingredient or scale_recipe; here a pattern does.

const HOW_MUCH = /^(?:how (?:much|many)|what amount of)\s+(?:of\s+)?(?:the\s+)?(.+?)(?:\s+(?:do|does|did|should|is|are|goes|go|in)\b.*)?$/;
const SCALE = new RegExp(
  `^(?:(?:make|scale)(?: it| this| the recipe)? (?:for|to)|(?:for|feed|serve)) (\\d+|${NUMBER_WORD})` +
  `(?: (?:servings?|people|portions|persons))?$`);

export function toolRoute(text) {
  const t = stripPolite(normalize(text));
  let m = SCALE.exec(t);
  if (m) return { tool: "scale_recipe", servings: /^\d+$/.test(m[1]) ? Number(m[1]) : WORD_VALUES[m[1]] };
  m = HOW_MUCH.exec(t);
  if (m) return { tool: "get_ingredient", name: m[1] };
  return null;
}
