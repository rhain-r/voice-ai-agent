// Interview Coach logic, ported from interview-coach/src so it runs in the browser with no server.

// -- mcp_server/bank.py: question plan -----------------------------------------------------------

export const LEVELS = ["intern", "junior", "mid", "senior", "staff"];

function shuffle(items, random) {
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}

// Items at the candidate's level first (shuffled), then the rest (shuffled) as top-up.
function orderedPool(items, level, random) {
  const matching = items.filter((q) => q.levels.includes(level));
  const others = items.filter((q) => !q.levels.includes(level));
  return [...shuffle(matching, random), ...shuffle(others, random)];
}

export function questionPlan(bank, family, level, style, count, random = Math.random) {
  const tag = (s) => (q) => ({ ...q, style: s });
  const behavioral = [...bank.general.behavioral, ...(family !== "general" ? bank[family].behavioral : [])];
  const pools = {
    behavioral: orderedPool(behavioral.map(tag("behavioral")), level, random),
    technical: orderedPool(bank[family].technical.map(tag("technical")), level, random),
  };
  const wanted = Array.from({ length: count }, (_, i) =>
    style === "mixed" ? (i % 2 === 0 ? "behavioral" : "technical") : style);
  const plan = [];
  for (const want of wanted) {
    const other = want === "behavioral" ? "technical" : "behavioral";
    const source = pools[want].length ? pools[want] : pools[other];
    if (!source.length) break;
    plan.push(source.shift());
  }
  return plan;
}

// -- agent/analytics.py: speech metrics only a voice interview can produce -----------------------

const FILLERS = /\b(?:um+|uh+|uhm|er|erm|hmm+)\b/gi;
const TICS = {
  "you know": /\byou know\b/gi,
  "kind of": /\bkind of\b/gi,
  "sort of": /\bsort of\b/gi,
  like: /\blike\b/gi,
  basically: /\bbasically\b/gi,
  literally: /\bliterally\b/gi,
};

export const countFillers = (text) => (text.match(FILLERS) ?? []).length;

export function countTics(text) {
  return Object.fromEntries(
    Object.entries(TICS).map(([name, re]) => [name, (text.match(re) ?? []).length]).filter(([, n]) => n));
}

export function paceBand(wpm) {
  if (wpm <= 0) return "n/a";
  if (wpm < 110) return "slow";
  if (wpm <= 170) return "conversational";
  return "fast";
}

const perMinute = (count, seconds) => (seconds > 0 ? count / (seconds / 60) : 0);
const round = (x, places) => Math.round(x * 10 ** places) / 10 ** places;
const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;

export class SpeechAnalytics {
  constructor() {
    this.questions = new Map(); // index -> {askedAt, segments: [{text, start, end}]}
    this.current = null;
    this.agent = []; // [start, end] intervals of the interviewer speaking
  }

  startQuestion(index, at) {
    if (!this.questions.has(index)) this.questions.set(index, { askedAt: at, segments: [] });
    this.current = index;
  }

  endQuestions() {
    this.current = null;
  }

  addSegment(seg) {
    if (this.current == null || !seg.text.trim()) return;
    this.questions.get(this.current).segments.push(seg);
  }

  addAgentSpeech(start, end) {
    if (end > start) this.agent.push([start, end]);
  }

  agentOverlaps(start, end) {
    return this.agent.some(([a, b]) => a < end && b > start);
  }

  answerMetrics(index) {
    const q = this.questions.get(index);
    const segments = [...(q?.segments ?? [])].sort((a, b) => a.start - b.start);
    if (!segments.length) {
      return { index, durationS: 0, wordCount: 0, wpm: 0, fillerCount: 0, fillersPerMin: 0, verbalTics: {},
        longestPauseS: 0, pausesOver3s: 0, thinkingTimeS: null, paceBand: "n/a" };
    }
    // The browser gives no word timings, so each final transcript segment is one timing unit.
    const units = segments.map((s) => [s.start, s.end]);
    const firstStart = units[0][0];
    const lastEnd = Math.max(...units.map(([, e]) => e));
    const duration = lastEnd - firstStart;

    const text = segments.map((s) => s.text).join(" ");
    const wordCount = text.split(/\s+/).filter(Boolean).length;
    const fillers = countFillers(text);
    const wpm = perMinute(wordCount, duration);

    const gaps = [];
    for (let i = 1; i < units.length; i++) {
      const [prevEnd, nextStart] = [units[i - 1][1], units[i][0]];
      if (nextStart > prevEnd && !this.agentOverlaps(prevEnd, nextStart)) gaps.push(nextStart - prevEnd);
    }

    const promptEnds = this.agent.map(([, e]) => e).filter((e) => q.askedAt <= e && e <= firstStart);
    const thinking = promptEnds.length ? round(firstStart - Math.max(...promptEnds), 2) : null;

    return {
      index,
      durationS: round(duration, 2),
      wordCount,
      wpm: round(wpm, 1),
      fillerCount: fillers,
      fillersPerMin: round(perMinute(fillers, duration), 2),
      verbalTics: countTics(text),
      longestPauseS: round(Math.max(0, ...gaps), 2),
      pausesOver3s: gaps.filter((g) => g > 3).length,
      thinkingTimeS: thinking,
      paceBand: paceBand(wpm),
      transcript: text,
    };
  }

  sessionMetrics() {
    const answers = [...this.questions.keys()].sort((a, b) => a - b).map((i) => this.answerMetrics(i));
    const spoken = answers.filter((a) => a.wordCount);
    const segs = [...this.questions.values()].flatMap((q) => q.segments);
    const candidateS = segs.reduce((sum, s) => sum + (s.end - s.start), 0);
    const agentS = this.agent.reduce((sum, [a, b]) => sum + (b - a), 0);
    const totalDuration = spoken.reduce((sum, a) => sum + a.durationS, 0);
    const thinking = answers.map((a) => a.thinkingTimeS).filter((t) => t != null);
    return {
      answers,
      avgWpm: spoken.length ? round(mean(spoken.map((a) => a.wpm)), 1) : 0,
      fillersPerMin: round(perMinute(spoken.reduce((sum, a) => sum + a.fillerCount, 0), totalDuration), 2),
      talkRatio: candidateS + agentS ? round(candidateS / (candidateS + agentS), 3) : 0,
      avgThinkingTimeS: thinking.length ? round(mean(thinking), 2) : null,
    };
  }
}

// -- demo-only end-of-answer check ----------------------------------------------------------------
// The full app uses LiveKit's semantic turn detector (0.8 s to 6 s). The demo approximates it: a
// sentence that trails off on a connective or filler gets the long wait, anything else a shorter one.

const TRAILING = new Set(["and", "but", "so", "because", "or", "um", "uh", "like", "the", "a", "an", "to", "of",
  "with", "then", "which", "that", "if", "when", "where", "while", "my", "our", "we", "i"]);

export function silenceBeforeTurnEnds(text) {
  const last = text.toLowerCase().replace(/[^a-z\s']/g, " ").trim().split(/\s+/).at(-1) ?? "";
  return TRAILING.has(last) ? 6.0 : 3.0;
}
