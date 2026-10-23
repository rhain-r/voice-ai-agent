# Interview Coach: design spec

**Date:** 2026-10-23
**Status:** Draft for review
**Sibling project:** `../kitchen-companion` (built separately, on a different stack)

## 1. Purpose

A voice agent that runs a realistic mock job interview for any role, then hands the candidate a scorecard. It is a portfolio piece: it should prove the builder can ship a production-shaped voice agent using the tools AI engineering and forward-deployed-engineer job posts ask for (Python, LiveKit Agents, Claude, MCP, LangGraph, FastAPI, evals, observability, Docker, Next.js).

### What success looks like

1. **It never cuts off a thinking candidate.** A 4-second pause mid-answer does not trigger a reply. A finished answer gets a reply within about 1.5 s.
2. **It interviews like a person.** It asks one question at a time, asks follow-ups when an answer is vague (most often a missing result), and doesn't coach mid-interview.
3. **It stops when interrupted.** If the candidate talks over it, it stops within roughly 300 ms. A cough or "mm-hmm" does not count as an interruption.
4. **It produces something useful.** Every finished session yields a scorecard with:
   - a grade per answer, with evidence quoted from the answer
   - speech metrics a text chatbot can't produce (pace, filler words, pauses, thinking time)
   - a short coaching plan
5. **It shows its work.** The live UI shows the transcript, agent state, question progress and latency for each turn.
6. **It is tested.** Unit tests run without keys. Agent behavior evals and a grader calibration check run with an Anthropic key.

### Non-goals (v1)

- Phone calls (LiveKit SIP is a documented stretch goal).
- Video, résumé upload, or questions taken from a real job posting.
- Multi-user accounts or auth. It runs locally, single user.
- Hosting or cloud deployment beyond Docker Compose.

## 2. Why this architecture fits the problem

| What the interview needs | What we build |
|---|---|
| A scheduled one-on-one session that could later be recorded or observed | **LiveKit Agents** on a LiveKit server (SFU rooms); the agent joins through explicit dispatch |
| Candidates pause to think | Semantic **turn detector** plus long maximum endpointing delay (~6 s) |
| Analytics need exact words, including fillers, plus timing | **Cascaded** pipeline: Deepgram Nova-3 STT (`filler_words` on) → Claude → TTS. A speech-to-speech model would lose this data. |
| Follow-ups must be smart; a short pause before replying is normal in interviews | **Claude Sonnet 5.5** for the live conversation |
| Grading must be careful and consistent; latency doesn't matter | A post-session **LangGraph** pipeline on **Claude Opus 5.5** |
| The question bank should be reusable outside this app | An **MCP server**, also usable from Claude Desktop or Claude Code |

## 3. Architecture

```
 Browser (Next.js, :3000)
   │  1. POST /api/sessions {role, level, style, count}
   ▼
 FastAPI (:8000) ── creates session row, mints LiveKit token with agent dispatch ──▶ returns {token, url, session_id}
   │                                                                  ▲
   │  5. GET /api/sessions/{id}/report  (polls)                       │ 4. POST /api/sessions/{id}/complete
   │                                                                  │    (transcript, answers, speech metrics)
 Browser ══ 2. WebRTC audio + text streams ══▶ LiveKit server (:7880) ◀══ 3. Agent worker (LiveKit Agents)
                                                                         ├─ Silero VAD + turn detector
                                                                         ├─ Deepgram Nova-3 STT
                                                                         ├─ Claude Sonnet 5.5 (fallback: Haiku 5.5)
                                                                         ├─ TTS: Deepgram Aura-2 (fallback: Cartesia, if keyed)
                                                                         └─ MCP client ──▶ MCP server (:8765) question bank
 FastAPI background task: LangGraph scorecard (Claude Opus 5.5) ──▶ SQLite ──▶ report
```

### Process boundaries

- **Agent worker:** real-time only. It never runs the scorecard, so it is ready for the next call as soon as one ends.
- **API:** owns persistence and post-processing. If the scorecard fails, the live call is unaffected.
- **MCP server:** owns the question bank and rubric. Both the agent and the API read from it.

## 4. Repository layout

```
interview-coach/
├─ pyproject.toml            # uv, Python 3.12
├─ .env.example
├─ docker-compose.yml        # livekit, mcp, api, agent, web
├─ src/interview_coach/
│  ├─ config.py              # pydantic-settings; startup check lists missing keys
│  ├─ agent/
│  │  ├─ worker.py           # entrypoint: session wiring, dispatch metadata, metrics, completion hook
│  │  ├─ interviewer.py      # Interviewer Agent: instructions, tools, stt_node observer
│  │  ├─ prompts.py          # voice rules + interviewer persona
│  │  ├─ analytics.py        # SpeechAnalytics (pure): per-answer + session speech metrics
│  │  ├─ speakable.py        # text normalizer applied before TTS
│  │  └─ telemetry.py        # per-turn latency aggregation, UI publishing, OTel setup
│  ├─ mcp_server/
│  │  ├─ server.py           # MCP server (streamable HTTP)
│  │  └─ question_bank.json
│  ├─ scorecard/
│  │  ├─ models.py           # pydantic: AnswerGrade, Scorecard, CoachingPlan
│  │  └─ graph.py            # LangGraph pipeline
│  └─ api/
│     ├─ main.py             # FastAPI app
│     └─ db.py               # SQLite persistence
├─ tests/
│  ├─ unit/                  # no API keys needed
│  └─ evals/                 # needs ANTHROPIC_API_KEY; marked `eval`
└─ web/                      # Next.js 16 (App Router, TypeScript)
```

## 5. Components

### 5.1 Agent worker (`agent/worker.py`)

- Registers with LiveKit under the agent name `interview-coach` (explicit dispatch only).
- Reads the session setup `{session_id, role, level, style, count}` from the job's dispatch metadata.
- Fetches the question plan from the MCP server at session start. If the server is unreachable, it falls back to the bundled `question_bank.json` and logs a warning.
- Builds the `AgentSession`:
  - **VAD:** Silero.
  - **Turn detection:** LiveKit turn-detector model. Minimum endpointing delay ~0.8 s; maximum ~6.0 s.
  - **Interruptions:** enabled. Require at least 2 words (so backchannels like "mm-hmm" are ignored). On a false interruption, resume after ~1.5 s.
  - **Preemptive generation:** on.
  - **User-away timeout:** ~25 s. When it fires, the agent checks in once ("Take your time — let me know when you're ready").
- **STT:** Deepgram Nova-3 with `filler_words=true`, `smart_format`, and keyterms taken from the role (e.g. "Kubernetes", "PostgreSQL").
- **LLM:** a FallbackAdapter of Claude Sonnet 5.5 → Claude Haiku 5.5.
- **TTS:** Deepgram Aura-2, plus Cartesia as a fallback when `CARTESIA_API_KEY` is set. `TTS_PROVIDER` selects the primary.
- On session end (the `end_interview` tool, or the candidate leaving), it POSTs the completion payload to the API using a shared secret header.

### 5.2 Interviewer agent (`agent/interviewer.py`)

**Instructions:**
- Persona: a warm, professional interviewer for the given role and level.
- Voice rules (shared): one or two sentences per turn, one question at a time, no lists or markdown, speakable numbers.
- Never gives feedback mid-interview; says feedback comes in the scorecard.
- Uses at most 2 follow-ups per question, each probing a missing STAR element (most often the result or impact).
- If the candidate asks to repeat or rephrase, does so without counting it as a follow-up.

**Flow:**
1. `on_enter`: greet, explain the format in one sentence ("five questions, take your time"), then call `next_question`.
2. Question loop, driven by tools.
3. After the last question: "Do you have any questions for me?" Answers in character, briefly.
4. Closes and calls `end_interview`.

**Tools:**

| Tool | Behavior |
|---|---|
| `next_question()` | Returns the next question (text, competency, and what a good answer covers) and marks an answer boundary in analytics. Returns `NO_MORE_QUESTIONS` when the plan is exhausted. |
| `end_interview(reason)` | `reason`: completed / candidate_requested / timeout. Says a closing line, finalizes analytics, triggers completion, then shuts the session down after the goodbye finishes playing. |

**`stt_node` override:** wraps the default STT node and forwards every final speech event (text plus timings) to `SpeechAnalytics`.

**`tts_node` override:** passes text through `speakable.normalize()` before synthesis.

### 5.3 Speech analytics (`agent/analytics.py`, pure, no I/O)

**Inputs:**
- final STT segments `(text, start_s, end_s, words?)`
- question boundaries `(index, asked_at_s)`
- agent speech intervals

Word-level timings are used when the STT event carries them. Otherwise metrics fall back to segment level: pauses become gaps between final segments.

**Metrics per answer:**
- `duration_s`, `word_count`, `wpm`
- `filler_count` and `fillers_per_min`. Fillers are *um, uh, er, erm, hmm*.
- `verbal_tics`: counts of *like, you know, basically, literally, kind of, sort of*. Reported separately because they are often legitimate.
- `longest_pause_s`, `pauses_over_3s`
- `thinking_time_s`: time from the end of the question to the candidate's first word.

**Session metrics:** averages of the above, plus `talk_ratio` (candidate speech ÷ total speech).

**Pace bands:** below 110 wpm is slow, 110–170 is conversational, above 170 is fast.

### 5.4 Speakable text (`agent/speakable.py`)

- Strips markdown (`*`, `#`, backticks, list bullets).
- Expands common symbols: `%` → "percent", `&` → "and", `e.g.` → "for example".
- Turns URLs into "the link on screen".
- Stays deterministic and table-tested.

### 5.5 Telemetry (`agent/telemetry.py`)

- Subscribes to the session's metrics events and assembles one record per agent turn: `eou_delay_ms`, `stt_ms` (if reported), `llm_ttft_ms`, `tts_ttfb_ms`, `total_ms`.
- Publishes each record to the room on the text-stream topic `coach.metrics`, along with `coach.progress` (`{index, total, competency}`).
- Includes p50/p95 of `total_ms` in the completion payload.
- When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, configures an OpenTelemetry OTLP exporter for LiveKit's built-in tracing (works with Langfuse, Jaeger and similar).

### 5.6 MCP server (`mcp_server/server.py`)

- Official `mcp` Python SDK, streamable HTTP at `:8765/mcp`.
- **Tools:**
  - `list_role_families()`
  - `get_question_plan(role, level, style, count)`: returns ordered items `{id, text, competency, good_answer_covers[]}`.
  - `get_rubric(style)`: returns the dimensions with 1–5 anchors.
- **Question bank:** role families are software engineering, data/analytics, AI/ML engineering, product management, design, and general. Each has behavioral and technical-conceptual items, tagged by level.
- **Unknown roles:** the plan mixes behavioral items with technical-conceptual items from the closest family. The closest family comes from a keyword map: "engineer", "developer" → software; "data", "analyst" → data; "ML", "AI", "machine learning" → AI/ML; "product manager" → product; "designer", "UX" → design. Anything unmatched → general.
- **Plan selection:** deterministic for a given seed (the session id), so plans are reproducible in tests.

### 5.7 Scorecard pipeline (`scorecard/graph.py`, LangGraph)

**State:** `{session, qa_items[], rubric, grades (reducer: append), summary, coaching}`

**QA item:** one question plus the whole exchange until the next question. That covers the candidate's turns and any follow-ups the agent asked. Grading judges the answer as finally developed, follow-ups included.

**Graph:**
1. `START`
2. `fan_out`: one `Send` per QA item
3. `grade_answer`: Claude Opus 5.5, structured output `AnswerGrade`
4. `aggregate`: pure Python
5. `coach`: Claude Opus 5.5, structured output `CoachingPlan`
6. `END`

**`AnswerGrade`:**
- scores 1–5 on `structure` (STAR), `specificity`, `impact`, `relevance` and `communication`
- `strengths[]` and `improvements[]`, each ≤ 2 items
- `evidence_quotes[]`: short excerpts from the answer that justify the grade
- `one_line_verdict`

**`aggregate`:**
- overall score from 0 to 100: the weighted mean of all dimensions, with structure and impact weighted ×1.5
- the weakest dimension
- the best and weakest answer

**`CoachingPlan`:**
- `top_fixes[3]`
- `rewritten_answer`: the weakest answer rewritten in STAR form, using only facts the candidate gave
- `practice_drill`

**Injection:** the LLM is injected (a factory parameter), so unit tests run the graph with a fake model.

### 5.8 API (`api/main.py`, FastAPI + SQLite)

| Endpoint | Purpose |
|---|---|
| `POST /api/sessions` | Validates setup, creates a session row and room name, mints a participant token whose room config dispatches `interview-coach` with the setup as metadata. Returns `{session_id, token, livekit_url}`. |
| `POST /api/sessions/{id}/complete` | Agent only (`X-Agent-Secret`). Stores the transcript, QA items, speech metrics and latency, then schedules the scorecard as a background task. |
| `GET /api/sessions/{id}/report` | `{status: pending\|ready\|failed, session, speech, scorecard?, error?}` |
| `POST /api/sessions/{id}/report/retry` | Re-runs a failed scorecard. |
| `GET /api/sessions` | History list. |
| `GET /api/health` | Liveness, plus whether keys are present (true/false only, never the values). |

**Persistence:** one SQLite file (`data/coach.db`) holding `sessions` and `reports` tables, with JSON columns for payloads.

### 5.9 Web (`web/`, Next.js 16 + `@livekit/components-react`)

**`/`: setup**
- role (free text with suggestions), level, style (behavioral / technical / mixed), question count (3 / 5 / 7)
- a mic check (live input meter)
- recent sessions

**`/session/[id]`: live interview**
- agent state orb (listening / thinking / speaking)
- "Question 2 of 5" with the competency tag
- live transcript, with interim user text shown faded
- a latency chip on each agent turn
- an "End interview" button

When the call ends, the page goes to the report.

**`/report/[id]`: scorecard**
- polls until the report is ready
- overall score and a bar chart of the dimensions (SVG)
- a card per question: grade, evidence quotes, strengths and improvements, speech metrics
- the coaching plan and the rewritten answer
- the session's latency summary

**Behavior:** if microphone permission is denied, the page explains how to allow it.

## 6. Data flow for one answer

1. The agent speaks question 2 and calls `next_question`, which sets `asked_at`. The UI gets a `coach.progress` update.
2. The candidate thinks for 3.1 s, which is recorded as `thinking_time`. The candidate pauses mid-answer for 2.4 s; the turn detector judges the sentence incomplete, so the agent waits.
3. The candidate finishes. End of turn is detected, and preemptive generation has already started the LLM. Sonnet streams a follow-up, TTS streams it, and the UI shows a latency chip (e.g. 1.1 s).
4. Each final STT segment goes to analytics, attributed to answer 2.
5. At session end, the payload goes to the API. The scorecard runs in about 20–40 s, and the report page renders it.

## 7. Error handling

| Failure | Behavior |
|---|---|
| Missing required keys | Agent, API and MCP each refuse to start and name the missing variables. |
| MCP server down | The agent uses the bundled bank. The API uses the bundled rubric. Both log a warning. |
| Primary LLM or TTS fails mid-call | The FallbackAdapter switches providers; the call continues. |
| STT disconnects | The LiveKit plugin reconnects. If it can't, the agent says it is having trouble hearing and ends gracefully. |
| Candidate leaves early | The completion payload is marked `partial`, and the scorecard grades only the answered questions. |
| Scorecard fails | The report has status `failed` with the error, but still shows the transcript and speech metrics. A retry endpoint exists. |
| Agent → API POST fails | Retried 3 times with backoff, then the payload is written to `data/failed_completions/` for manual replay. |

## 8. Testing

**Unit tests** (`tests/unit`, no keys, run in CI on every push):
- `analytics`: word-level and segment-level inputs, filler and tic counting, pauses, thinking time, talk ratio, pace bands.
- `speakable`: a table of inputs to expected outputs.
- `mcp_server`: plan size, level filtering, deterministic seeding, unknown-role mix, rubric shape.
- `scorecard`: graph run with a fake LLM, covering fan-out count, aggregation math and partial sessions.
- `api`: session creation (the token decodes with the dispatch present), the completion auth check, the report state machine.

**Behavior evals** (`tests/evals`, need `ANTHROPIC_API_KEY`, `pytest -m eval`). These use the LiveKit Agents text-mode test harness with an LLM judge:
- greets, explains the format, and asks the first question (calls `next_question`)
- a vague answer with no result gets a follow-up about outcome or impact
- asking "how did I do?" mid-interview gets a deferral to the scorecard, not feedback
- an off-topic request ("write me a poem") gets a polite redirect, still in character
- every reply is 3 sentences or fewer with no markdown (judge plus regex)
- "I need to stop" calls `end_interview(candidate_requested)`

**Grader calibration eval:**
- Fixture pairs of a strong and a weak answer to the same question.
- The strong answer's overall score must beat the weak one's by at least 15 points.
- Runs 3 times to check stability.

**Web:** `tsc --noEmit` and `next build`.

## 9. Configuration (`.env.example`)

```
ANTHROPIC_API_KEY=
DEEPGRAM_API_KEY=
CARTESIA_API_KEY=            # optional TTS fallback
TTS_PROVIDER=deepgram        # deepgram | cartesia
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
MCP_URL=http://localhost:8765/mcp
API_URL=http://localhost:8000
AGENT_SHARED_SECRET=change-me
LIVE_MODEL=claude-sonnet-5-5
FALLBACK_MODEL=claude-haiku-5-5
GRADER_MODEL=claude-opus-5-5
OTEL_EXPORTER_OTLP_ENDPOINT= # optional
```

## 10. Running

- **Everything in Docker:** `docker compose up`. This runs `livekit/livekit-server --dev` plus the MCP, API, agent and web services.
- **Development:** run `livekit-server` in Docker, the Python services with `uv run`, and the web app with `npm run dev`.
- **CI:** one GitHub Actions job, filtered to this folder, runs the unit tests, a lint (ruff), and the web build. A second job runs evals when the `ANTHROPIC_API_KEY` secret is present.

## 11. Decisions

- The scorecard runs in the API, not the agent, to keep the real-time process lean.
- The question plan is fetched by code (an MCP client) at session start, not by the LLM calling MCP tools. Progression must be deterministic and testable.
- No auth in v1: it is a local single-user demo, and the agent→API path uses a shared secret.
