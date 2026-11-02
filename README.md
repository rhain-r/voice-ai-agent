# Voice AI Agents: Interview Coach and Kitchen Companion

Two real-time voice agents built with Claude, each designed around how people actually speak in one setting: a mock job interview and a busy kitchen. The Interview Coach (LiveKit Agents) waits patiently through thinking pauses and grades every answer, while the Kitchen Companion (Pipecat) answers short hands-free commands and ignores conversation not addressed to it. Both stream speech end to end, compute quantities and timings in code rather than in the model, and are tested without API keys.

---

## Try it out!

| [Live &rarr;](https://rhain-r.github.io/voice-ai-agent/demo/) | Both agents in your browser, no account or API key |
| --- | --- |

The live demo runs each project's deterministic code, ported to JavaScript, with the browser's own speech recognition and voice. Use Chrome, Edge or Safari to speak (Firefox can type), and note that turns which need Claude in the full app are labelled rather than answered.

---

## Project Overview

| | Interview Coach | Kitchen Companion |
| :--- | :--- | :--- |
| Problem | Practising interviews out loud with honest feedback | Following a recipe with hands covered in flour |
| Setting | Focused one-on-one session with long thinking pauses | Noisy shared room with short commands and timers |
| Framework | LiveKit Agents with a LiveKit server | Pipecat with peer-to-peer WebRTC |
| Turn-taking | Patient: waits up to 6 s through mid-answer pauses | Fast, and only answers when addressed ("Chef, ...") |
| Model | Claude Sonnet 5.5 live, Claude Opus 5.5 for grading | Code for common commands, Claude Haiku 5.5 otherwise |
| Output | Per-answer scorecard with speech analytics | Spoken steps, quantities, conversions and timers |

---

## Methodology

Each agent is a cascaded pipeline (speech-to-text, Claude, text-to-speech) so that exact words and timings stay available for analysis. Design decisions follow the qualities users notice first in a voice agent, in order of importance:

1. **Speed.** Every stage streams, and each reply's latency is measured and shown on screen.
2. **Turn-taking.** The agent judges whether the speaker has finished, not merely how long they have been silent.
3. **Interruptions.** Speaking over the agent stops it, while "mm-hmm" and kitchen noise do not.
4. **Written for the ear.** Replies are one or two sentences, and "1 1/2 cups" is spoken as "one and a half cups".
5. **Tools, not memory.** Questions come from an MCP server, and quantities, conversions and timers come from deterministic code.
6. **Graceful recovery.** The LLM and text-to-speech fail over to a second provider mid-call, a dropped interview still yields a partial scorecard, and kitchen timers survive a reconnect.
7. **Measurement.** Unit tests run without keys, and evals run against the real model with an LLM judge.

---

## Agent Capabilities

**Interview Coach**
* **Semantic turn detection:** Waits through a thinking pause but replies within about a second once the answer is complete.
* **Question bank over MCP:** Role-, level- and style-aware questions that Claude Desktop or Claude Code can also use.
* **Speech analytics:** Pace, filler words, verbal tics, longest pause and thinking time for every answer.
* **Structured grading:** A LangGraph map-reduce on Claude Opus 5.5 scores five rubric dimensions, quotes the candidate, and writes a coaching plan.

**Kitchen Companion**
* **Attention gate:** Responds only to the wake word "Chef", a follow-up within 8 s, a button tap, or "stop" while speaking.
* **Fast path:** "Next", "go back", "step three" and timer commands are answered in code with no LLM call.
* **Deterministic kitchen maths:** Scaling, unit conversion and spoken fractions come from table-tested code; the model is told never to guess.
* **Self-announcing timers:** Timers wait for a quiet moment to speak and repeat a reminder until acknowledged.
* **Recipe import:** Any recipe URL with schema.org JSON-LD can be imported behind an SSRF guard.

---

## Agentic Architecture Overview

```text
Interview Coach

[ Browser: Next.js ] ══ WebRTC ══► [ LiveKit server ] ◄══ [ Agent worker: LiveKit Agents ]
                                                             │
                     Deepgram STT ─► Claude Sonnet 5.5 ─► Deepgram TTS
                                          │
                                          └─ Tool: next_question ◄── [ MCP question bank ]
                                                             │
                                                             ▼  transcript + speech metrics
                     [ FastAPI ] ─► [ LangGraph scorecard: Claude Opus 5.5 ] ─► Report
```

```text
Kitchen Companion

[ Tablet PWA: Vite + React ] ══ SmallWebRTC ══► [ Bot server: FastAPI + Pipecat ]
                                                             │
Deepgram STT ─► Attention gate ─► Fast path ──── matched ───────────────────────┐
                 (not addressed:      │                                          ▼
                  ignored)            └─ other ─► Claude Haiku 5.5 + 9 tools ─► Speakable filter ─► TTS

Per-kitchen state that survives reconnects: recipe position, scale, timers, queued announcements
```

---

## Evaluation

| Project | Without API keys | Against the real Claude API |
| :--- | :--- | :--- |
| Interview Coach | 116 unit tests: analytics, MCP server, LangGraph pipeline, API, turn-taking settings | LLM-judge behaviour evals and a grader calibration check (strong answers must outscore weak ones by 15+ points) |
| Kitchen Companion | Unit and pipeline tests: ~80 fast-path phrasings, units, timers, importer SSRF guard | Tool-call evals, such as "make it for eight people" calling `scale_recipe(8)` |

Continuous integration runs lint, tests and web builds on every change, and runs the evals when an `ANTHROPIC_API_KEY` secret is set.

---

## Tech Stack

| Component | Technology |
| :--- | :--- |
| Voice frameworks | LiveKit Agents, Pipecat |
| Language models | Claude Sonnet 5.5, Claude Opus 5.5, Claude Haiku 5.5 |
| Speech | Deepgram Nova-3 (speech-to-text), Deepgram Aura-2 with Cartesia fallback (text-to-speech) |
| Orchestration and tools | LangGraph, Model Context Protocol (MCP) |
| Backend | Python 3.12, FastAPI, SQLite |
| Frontend | Next.js, Vite + React (PWA) |
| Testing and delivery | pytest, Node test runner, GitHub Actions, Docker Compose |

---

## Repository Structure

```text
.github/workflows/      CI for each project
demo/                   Live browser demo (GitHub Pages)
interview-coach/
    src/interview_coach/
        agent/          Interviewer, prompts, analytics, telemetry, LLM fallback
        mcp_server/     MCP server and question bank
        scorecard/      LangGraph grading pipeline
        api/            FastAPI app and SQLite store
    web/                Next.js interview and report UI
    tests/              Unit tests and Claude-backed evals
    docs/               Design spec and implementation plan
kitchen-companion/
    src/kitchen_companion/
        pipeline/       Attention gate, fast path, speakable filter, state note
        recipes/        Recipe library, ingredient parser, units, importer
        timers.py       Timer service and announcements
        tools.py        Claude tool handlers
    web/                Tablet PWA cook mode
    tests/              Unit, pipeline and eval tests
    docs/               Design spec and implementation plan
LICENSE
README.md
```

---

## Running Locally

Each project needs an Anthropic API key and a Deepgram API key, both of which offer free credits. Copy `.env.example` to `.env`, add the keys, and start the project with Docker; each project's own README covers development setup.

```bash
cd interview-coach && cp .env.example .env && docker compose up --build
```

```bash
cd kitchen-companion && cp .env.example .env && docker compose up --build
```

---

## License

MIT. See [LICENSE](LICENSE).
