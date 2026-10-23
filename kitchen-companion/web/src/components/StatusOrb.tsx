import type { Activity, Connection } from "../lib/types";

const LABELS: Record<Activity, string> = {
  idle: "Ready",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

type Props = { activity: Activity; connection: Connection };

export function StatusOrb({ activity, connection }: Props) {
  const state = connection === "ready" ? activity : "offline";
  const label = connection === "ready" ? LABELS[activity] : connection === "connecting" ? "Connecting" : "Reconnecting";
  return (
    <div className="status" role="status" aria-live="polite">
      <span className={`orb ${state}`} aria-hidden="true" />
      <span className="status-label">{label}</span>
    </div>
  );
}
