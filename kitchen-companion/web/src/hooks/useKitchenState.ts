import { useReducer } from "react";
import type { Activity, Connection, Latency, RecipeState, ServerMessage, TimerSnap, TranscriptLine } from "../lib/types";

const MAX_LINES = 30;

export type KitchenState = {
  recipe: RecipeState | null;
  timers: TimerSnap[];
  transcript: TranscriptLine[];
  activity: Activity;
  connection: Connection;
  error: string | null;
  // Ingredient ticks are local to this screen, keyed "recipeId:index".
  checked: Record<string, boolean>;
  // A latency event can arrive just before the reply it measures.
  pendingLatency: Latency | null;
  replyOpen: boolean;
  nextId: number;
};

export type KitchenAction =
  | { kind: "server"; message: ServerMessage }
  | { kind: "activity"; activity: Activity }
  | { kind: "botStarted" }
  | { kind: "botStopped" }
  | { kind: "reply"; text: string }
  | { kind: "connection"; connection: Connection }
  | { kind: "toggleIngredient"; key: string }
  | { kind: "dismissError" };

export const initialKitchenState: KitchenState = {
  recipe: null,
  timers: [],
  transcript: [],
  activity: "idle",
  connection: "connecting",
  error: null,
  checked: {},
  pendingLatency: null,
  replyOpen: false,
  nextId: 1,
};

function addLine(state: KitchenState, line: Omit<TranscriptLine, "id">): KitchenState {
  const transcript = [...state.transcript, { ...line, id: state.nextId }].slice(-MAX_LINES);
  return { ...state, transcript, nextId: state.nextId + 1 };
}

function lastReplyIndex(lines: TranscriptLine[]): number {
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].kind === "reply") return i;
    if (lines[i].kind === "heard") return -1; // a newer question; the reply hasn't started yet
  }
  return -1;
}

function onServer(state: KitchenState, message: ServerMessage): KitchenState {
  switch (message.type) {
    case "recipe_state": {
      const sameRecipe = state.recipe?.id === message.recipe.id;
      return { ...state, recipe: message.recipe, checked: sameRecipe ? state.checked : {} };
    }
    case "timers":
      return { ...state, timers: message.timers };
    case "heard":
      return addLine({ ...state, replyOpen: false }, { kind: "heard", text: message.text });
    case "overheard":
      return addLine(state, { kind: "overheard", text: message.text });
    case "latency": {
      const latency = { path: message.path, ms: message.ms };
      const i = lastReplyIndex(state.transcript);
      if (i >= 0 && state.replyOpen && !state.transcript[i].latency) {
        const transcript = state.transcript.map((line, j) => (j === i ? { ...line, latency } : line));
        return { ...state, transcript };
      }
      return { ...state, pendingLatency: latency };
    }
    case "error":
      return { ...state, error: message.message };
  }
}

export function kitchenReducer(state: KitchenState, action: KitchenAction): KitchenState {
  switch (action.kind) {
    case "server":
      return onServer(state, action.message);
    case "activity":
      return { ...state, activity: action.activity };
    case "botStarted":
      // Reply text can arrive before the audio starts, so a reply line stays open until the bot stops.
      return { ...state, activity: "speaking" };
    case "botStopped":
      return { ...state, activity: "idle", replyOpen: false };
    case "reply": {
      const text = action.text.trim();
      if (!text) return state;
      const i = lastReplyIndex(state.transcript);
      if (state.replyOpen && i >= 0) {
        const transcript = state.transcript.map((line, j) =>
          j === i ? { ...line, text: `${line.text} ${text}` } : line,
        );
        return { ...state, transcript };
      }
      const next = addLine(state, { kind: "reply", text, latency: state.pendingLatency ?? undefined });
      return { ...next, replyOpen: true, pendingLatency: null };
    }
    case "connection":
      return {
        ...state,
        connection: action.connection,
        activity: action.connection === "ready" ? state.activity : "idle",
      };
    case "toggleIngredient":
      return { ...state, checked: { ...state.checked, [action.key]: !state.checked[action.key] } };
    case "dismissError":
      return { ...state, error: null };
  }
}

export function useKitchenState() {
  return useReducer(kitchenReducer, initialKitchenState);
}
