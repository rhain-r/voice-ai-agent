// Shapes of the bot server's REST responses and RTVI server messages (see events.py).

export type RecipeSummary = {
  id: string;
  title: string;
  servings: number;
  total_time_min: number | null;
};

export type IngredientRow = { text: string; checked: boolean };

export type RecipeState = {
  id: string | null;
  title: string | null;
  index: number;
  total: number;
  servings: number | null;
  steps: string[];
  ingredients: IngredientRow[];
};

export type TimerSnap = {
  id: string;
  label: string;
  state: "running" | "due" | "acknowledged" | "cancelled";
  minutes: number;
  ends_at_epoch: number;
};

export type Path = "fast" | "llm";
export type Latency = { path: Path; ms: number };

export type TranscriptLine = {
  id: number;
  kind: "heard" | "overheard" | "reply";
  text: string;
  latency?: Latency;
};

export type ServerMessage =
  | { type: "recipe_state"; recipe: RecipeState }
  | { type: "timers"; timers: TimerSnap[] }
  | { type: "heard"; text: string }
  | { type: "overheard"; text: string }
  | { type: "latency"; path: Path; ms: number }
  | { type: "error"; message: string };

// What the voice loop is doing right now, for the status orb.
export type Activity = "idle" | "listening" | "thinking" | "speaking";

export type Connection = "connecting" | "ready" | "reconnecting";
