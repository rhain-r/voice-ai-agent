// Mirrors the API (src/interview_coach/api/main.py) and the agent's text-stream payloads.

export type Level = "intern" | "junior" | "mid" | "senior" | "staff";
export type Style = "behavioral" | "technical" | "mixed";

export interface SessionSetup {
  role: string;
  level: Level;
  style: Style;
  count: number;
}

export interface CreatedSession {
  session_id: string;
  token: string;
  livekit_url: string;
}

/** coach.progress */
export interface Progress {
  index: number;
  total: number;
  competency: string;
}

/** coach.metrics */
export interface TurnLatency {
  speech_id: string;
  eou_delay_ms: number;
  llm_ttft_ms: number;
  tts_ttfb_ms: number;
  total_ms: number;
}

export type Dimension = "structure" | "specificity" | "impact" | "relevance" | "communication";

export interface AnswerGrade {
  scores: Record<Dimension, number>;
  strengths: string[];
  improvements: string[];
  evidence_quotes: string[];
  one_line_verdict: string;
}

export interface Scorecard {
  overall: number;
  dimension_averages: Record<Dimension, number>;
  weakest_dimension: Dimension;
  best_index: number;
  weakest_index: number;
  skipped: number[];
  graded: { index: number; grade: AnswerGrade }[];
  coaching: { top_fixes: string[]; rewritten_answer: string; practice_drill: string };
}

export interface AnswerMetrics {
  index: number;
  duration_s: number;
  word_count: number;
  wpm: number;
  filler_count: number;
  fillers_per_min: number;
  verbal_tics: Record<string, number>;
  longest_pause_s: number;
  pauses_over_3s: number;
  thinking_time_s: number | null;
  pace_band: "slow" | "conversational" | "fast" | "n/a";
}

export interface QAItem {
  index: number;
  question: string;
  competency: string;
  transcript: string;
  metrics: Partial<AnswerMetrics>;
}

export interface SpeechSummary {
  avg_wpm: number;
  fillers_per_min: number;
  talk_ratio: number;
  avg_thinking_time_s: number | null;
}

export interface Report {
  status: "in_progress" | "pending" | "ready" | "failed";
  session: {
    id: string;
    created_at: number;
    setup: SessionSetup;
    completion_status: "completed" | "partial" | null;
  };
  speech: SpeechSummary | null;
  latency: { p50_ms: number; p95_ms: number; turns: number } | null;
  transcript: { role: "user" | "assistant"; text: string; at: number }[];
  qa_items: QAItem[];
  scorecard: Scorecard | null;
  error: string | null;
}

export interface SessionSummary {
  session_id: string;
  created_at: number;
  setup: SessionSetup;
  completion_status: string | null;
  report_status: string | null;
  overall: number | null;
}
