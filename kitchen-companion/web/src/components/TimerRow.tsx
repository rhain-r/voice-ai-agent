import { useEffect, useState } from "react";
import type { TimerSnap } from "../lib/types";

type Props = { timers: TimerSnap[]; onAck: () => void };

function clock(secondsLeft: number): string {
  const s = Math.max(0, Math.ceil(secondsLeft));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

// Countdowns tick locally from each timer's end time; the server only says when they start and end.
export function TimerRow({ timers, onAck }: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (timers.length === 0) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [timers.length]);

  if (timers.length === 0) {
    return <p className="timers-empty">Say “Chef, set a timer for 8 minutes.”</p>;
  }
  return (
    <ul className="timers" aria-label="Timers">
      {timers.map((t) => {
        const left = (t.ends_at_epoch * 1000 - now) / 1000;
        const due = t.state === "due" || left <= 0;
        const state = due ? "due" : left < 60 ? "soon" : "running";
        return (
          <li key={t.id}>
            <button
              type="button"
              className={`timer ${state}`}
              onClick={due ? onAck : undefined}
              aria-disabled={!due}
              aria-label={due ? `${t.label} timer is done. Tap to dismiss.` : `${t.label}, ${clock(left)} left`}
            >
              <span className="timer-label">{t.label}</span>
              <span className="timer-clock">{due ? "Done" : clock(left)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
