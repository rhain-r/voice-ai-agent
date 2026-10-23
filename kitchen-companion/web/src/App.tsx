import { type BotOutputData, PipecatClient } from "@pipecat-ai/client-js";
import { PipecatClientAudio, PipecatClientProvider } from "@pipecat-ai/client-react";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CookMode } from "./components/CookMode";
import { RecipePicker } from "./components/RecipePicker";
import { TranscriptDrawer } from "./components/TranscriptDrawer";
import { useKitchenState } from "./hooks/useKitchenState";
import { useWakeLock } from "./hooks/useWakeLock";
import { kitchenId } from "./lib/kitchenId";
import type { ServerMessage } from "./lib/types";

// Reconnect delays after a drop: 1 s, 2 s, then every 5 s while the page is visible.
const BACKOFF_MS = [1000, 2000, 5000];

function isServerMessage(data: unknown): data is ServerMessage {
  return typeof data === "object" && data !== null && typeof (data as { type?: unknown }).type === "string";
}

function isNewSpokenSentence(data: BotOutputData): boolean {
  const kind = data.text_type ?? data.aggregated_by;
  return (kind === undefined || kind === "sentence") && (data.spoken_status ?? "new") === "new";
}

export function App() {
  const [state, dispatch] = useKitchenState();
  const [picking, setPicking] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const dropped = useRef<() => void>(() => undefined);

  const client = useMemo(
    () =>
      new PipecatClient({
        transport: new SmallWebRTCTransport(),
        enableMic: true,
        enableCam: false,
        callbacks: {
          onBotReady: () => dispatch({ kind: "connection", connection: "ready" }),
          onDisconnected: () => dropped.current(),
          onServerMessage: (data: unknown) => {
            if (isServerMessage(data)) dispatch({ kind: "server", message: data });
          },
          onUserStartedSpeaking: () => dispatch({ kind: "activity", activity: "listening" }),
          onUserStoppedSpeaking: () => dispatch({ kind: "activity", activity: "thinking" }),
          onBotStartedSpeaking: () => dispatch({ kind: "botStarted" }),
          onBotStoppedSpeaking: () => dispatch({ kind: "botStopped" }),
          onBotOutput: (data: BotOutputData) => {
            if (isNewSpokenSentence(data)) dispatch({ kind: "reply", text: data.text });
          },
        },
      }),
    [dispatch],
  );

  // Connect on load and keep reconnecting with the same kitchen_id, so the recipe and timers resume.
  useEffect(() => {
    let attempt = 0;
    let timer: number | undefined;
    let busy = false;
    let stopped = false;

    const connect = async () => {
      window.clearTimeout(timer);
      if (stopped || busy || document.visibilityState !== "visible") return;
      busy = true;
      dispatch({ kind: "connection", connection: attempt === 0 ? "connecting" : "reconnecting" });
      try {
        await client.connect({
          webrtcRequestParams: {
            endpoint: `${window.location.origin}/api/offer`,
            requestData: { kitchen_id: kitchenId() },
          },
        });
        attempt = 0;
      } catch {
        retry();
      } finally {
        busy = false;
      }
    };

    const retry = () => {
      if (stopped) return;
      dispatch({ kind: "connection", connection: "reconnecting" });
      const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      window.clearTimeout(timer);
      timer = window.setTimeout(connect, delay);
    };

    const onVisible = () => {
      if (document.visibilityState === "visible" && client.state !== "ready" && !busy) {
        attempt = Math.max(attempt, 1);
        void connect();
      }
    };

    dropped.current = retry;
    document.addEventListener("visibilitychange", onVisible);
    void connect();
    return () => {
      stopped = true;
      dropped.current = () => undefined;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      void client.disconnect();
    };
  }, [client, dispatch]);

  const send = useCallback(
    (type: string, data?: unknown) => {
      if (client.state !== "ready") return;
      try {
        client.sendClientMessage(type, data);
      } catch {
        // Dropped mid-send: the reconnect loop takes over.
      }
    },
    [client],
  );

  const recipeId = state.recipe?.id ?? null;
  useEffect(() => {
    if (recipeId) setPicking(false);
  }, [recipeId]);

  const cooking = !picking && !!state.recipe?.id;
  useWakeLock(cooking);

  return (
    <PipecatClientProvider client={client}>
      <PipecatClientAudio />
      {cooking && state.recipe ? (
        <CookMode
          state={state}
          recipe={state.recipe}
          dispatch={dispatch}
          send={send}
          onChangeRecipe={() => setPicking(true)}
          onOpenTranscript={() => setDrawerOpen(true)}
        />
      ) : (
        <RecipePicker
          ready={state.connection === "ready"}
          currentTitle={state.recipe?.title ?? null}
          onPick={(id) => {
            send("load_recipe", { id });
            if (id === recipeId) setPicking(false);
          }}
          onBack={state.recipe?.id ? () => setPicking(false) : null}
        />
      )}
      <TranscriptDrawer open={drawerOpen} lines={state.transcript} onClose={() => setDrawerOpen(false)} />
    </PipecatClientProvider>
  );
}
