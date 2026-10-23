"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { MicCheck } from "@/components/MicCheck";
import { createSession, listSessions, saveConnection } from "@/lib/api";
import type { Level, SessionSummary, Style } from "@/lib/types";

const ROLE_SUGGESTIONS = ["Software Engineer", "Data Analyst", "Product Manager", "ML Engineer", "UX Designer"];
const LEVELS: Level[] = ["intern", "junior", "mid", "senior", "staff"];
const LEVEL_LABEL: Record<Level, string> = {
  intern: "an intern",
  junior: "a junior",
  mid: "a mid-level",
  senior: "a senior",
  staff: "a staff",
};

export default function SetupPage() {
  const router = useRouter();
  const [role, setRole] = useState("");
  const [level, setLevel] = useState<Level>("junior");
  const [count, setCount] = useState(5);
  const [style, setStyle] = useState<Style>("behavioral");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<SessionSummary[]>([]);

  useEffect(() => {
    listSessions()
      .then(setHistory)
      .catch(() => setHistory([]));
  }, []);

  async function start(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = role.trim();
    if (trimmed.length < 2) {
      setError("Type the role you're interviewing for, like Data Analyst.");
      return;
    }
    setStarting(true);
    setError(null);
    try {
      const session = await createSession({ role: trimmed, level, style, count });
      saveConnection(session);
      router.push(`/session/${session.session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the interview.");
      setStarting(false);
    }
  }

  return (
    <main className="page">
      <h1>Practice an interview out loud.</h1>
      <p className="lede">
        Answer by speaking, the way you would in the real thing. Take your time to think. At the end you get feedback
        on every answer and on how you sounded.
      </p>

      <form onSubmit={start}>
        <p className="sentence">
          I&apos;m interviewing for{" "}
          <input
            aria-label="Role"
            list="roles"
            placeholder="a role"
            value={role}
            maxLength={80}
            onChange={(e) => setRole(e.target.value)}
          />
          <datalist id="roles">
            {ROLE_SUGGESTIONS.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>{" "}
          as{" "}
          <select aria-label="Level" value={level} onChange={(e) => setLevel(e.target.value as Level)}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {LEVEL_LABEL[l]}
              </option>
            ))}
          </select>{" "}
          candidate. Ask me{" "}
          <select aria-label="Number of questions" value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {[3, 5, 7].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>{" "}
          <select aria-label="Question style" value={style} onChange={(e) => setStyle(e.target.value as Style)}>
            <option value="behavioral">behavioral</option>
            <option value="technical">technical</option>
            <option value="mixed">mixed</option>
          </select>{" "}
          questions.
        </p>

        <div className="actions">
          <button className="button" type="submit" disabled={starting}>
            {starting ? "Starting…" : "Start interview"}
          </button>
          <MicCheck />
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>

      {history.length > 0 && (
        <section className="history" aria-labelledby="history-title">
          <h2 id="history-title">Past interviews</h2>
          <ul>
            {history.map((s) => (
              <li key={s.session_id}>
                <Link href={`/report/${s.session_id}`}>
                  <span className="role">
                    {s.setup.role}, {s.setup.level}
                  </span>
                  <span className="muted num">
                    {s.overall != null ? `${s.overall}/100` : statusLabel(s)}
                    {"  "}
                    {new Date(s.created_at * 1000).toLocaleDateString()}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

function statusLabel(s: SessionSummary) {
  if (!s.completion_status) return "Not finished";
  if (s.report_status === "failed") return "Scorecard failed";
  return "Scoring…";
}
