# Voice AI agents: two problems, two stacks

Two production-shaped voice agents, each built around how it's actually used:

| | [Interview Coach](interview-coach/) | [Kitchen Companion](kitchen-companion/) |
|---|---|---|
| **The problem** | Practicing interviews out loud, with honest feedback | Following a recipe when your hands are covered in flour |
| **How it's used** | A focused one-on-one session; you pause to think; you want to be evaluated | Ambient and hands-busy, in a noisy, shared room; short commands, long silences, timers |
| **Framework** | LiveKit Agents, with rooms on a LiveKit server | Pipecat, peer-to-peer WebRTC with no media server |
| **Turn-taking** | Patient: waits through thinking pauses | Snappy, and only answers when addressed ("Chef, …") |
| **Brain** | Claude Sonnet 5.5 live, Opus 5.5 for grading | Common commands handled in code, Claude Haiku 5.5 for everything else |
| **Also uses** | MCP question bank, LangGraph scorecard, FastAPI, Next.js | Recipe import from any URL, a timer service, a Vite + React tablet app |

## What makes a voice agent good

These are the things people notice, roughly in order, and where each project deals with them.

1. **Speed.** Replies should start within about a second of you finishing. Every stage streams, the model is tuned for first-token latency, and each reply's latency is measured and shown on screen.
   - Coach: preemptive generation, plus Sonnet 5.5 with thinking off and low effort.
   - Kitchen: "next", "back" and timer commands skip the LLM entirely.
2. **Turn-taking that fits the situation.** The question is when the user has finished, not how long they've been silent.
   - Coach: a semantic turn detector waits up to six seconds through a mid-answer pause.
   - Kitchen: replies fast, but ignores people talking to each other.
3. **Interruptions.** Talk over it and it stops. "Mm-hmm" and kitchen noise don't count.
4. **Written for the ear.** One or two sentences, one question at a time, no markdown read aloud. "1 1/2 cups" is spoken as "one and a half cups".
5. **Real work through tools, with no dead air.**
   - Coach: questions come from an MCP server.
   - Kitchen: quantities, unit conversion and timers come from deterministic code, never from the model's memory.
6. **Recovering gracefully.**
   - Both: the LLM and text-to-speech fall back to another provider mid-call.
   - Coach: the question bank falls back to a bundled copy, and a dropped call still produces a partial scorecard.
   - Kitchen: timers and recipe position survive a reconnect.
7. **Measured, not guessed.** Unit tests run without API keys. Evals run against the real model with an LLM judge, and each turn's latency is broken down.

## Run them

Each project is self-contained, with its own README, `.env.example`, `docker-compose.yml`, tests and CI workflow. Both need an Anthropic API key and a Deepgram API key; both have free credits.

```bash
cd interview-coach && cp .env.example .env && docker compose up --build
```

```bash
cd kitchen-companion && cp .env.example .env && docker compose up --build
```

Design specs and implementation plans are under each project's `docs/` folder.
