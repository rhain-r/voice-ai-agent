# Kitchen Companion: design spec

**Date:** 2026-10-23
**Status:** Draft for review
**Sibling project:** `../interview-coach` (built separately, on a different stack)

## 1. Purpose

A hands-free cooking assistant for a tablet propped up on the counter. It walks you through any recipe step by step, answers "how much butter again?", scales and converts quantities, and runs timers that speak up on their own. It is a portfolio piece built on **Pipecat**, chosen deliberately as the counterpart to the LiveKit-based Interview Coach. It proves the builder can design a voice agent around a hard environment, not just around a conversation.

### What success looks like

1. **It doesn't react to the room.** People chatting in the kitchen don't trigger replies. It responds when addressed ("Chef, …"), during a short window after it spoke, or when the big button is tapped.
2. **Common commands are instant.** "Next", "back", "repeat", "go to step 3" and timer commands are answered from code, without an LLM call. Target: under 500 ms from end of speech to first audio.
3. **It's right about quantities.** Ingredient amounts, scaling and unit conversions come from deterministic code, never from the LLM's memory.
4. **Timers behave like a good sous-chef.** They announce themselves, wait if you're mid-sentence, and repeat a reminder until you acknowledge them.
5. **It works with recipes you actually use.** It ships with a small library, and you can paste a recipe URL from most recipe sites.
6. **It's readable from across the counter.** Huge type, high contrast, and the screen stays awake.
7. **It is tested.** Unit tests and pipeline tests run without keys. Tool-call evals run with an Anthropic key.

### Non-goals (v1)

- Multiple simultaneous users or devices per kitchen.
- On-device wake-word models (the wake phrase is detected from the STT transcript).
- Nutrition data, shopping lists, meal planning.
- Native mobile apps; the web app is installable as a PWA.

## 2. Why this architecture fits the problem

| What the kitchen needs | What we build |
|---|---|
| One device, one bot, no rooms | **Pipecat** with **SmallWebRTC** (direct peer-to-peer WebRTC). No media server to run. |
| A noisy, shared room | An **attention gate** processor plus a higher interruption threshold, and browser noise suppression on the mic |
| Most utterances are tiny commands | A **fast-path router** answers them from code, so the LLM is only used for real questions |
| Hard numbers (quantities, temperatures, times) | A **recipe state machine** plus a unit converter: deterministic and table-tested |
| Things happen on a clock | A **timer service** that injects speech into the pipeline unprompted |
| Ingredient names are easy to mishear | Deepgram Nova-3 **keyterms** taken from the loaded recipe |
| Short, quick answers | **Claude Haiku 5.5** |
| A tablet propped on a counter | A **Vite + React PWA** with Screen Wake Lock and a large-type layout |
| Recipes live on the web | **Import by URL**, parsing the page's schema.org `Recipe` JSON-LD |

## 3. Architecture

```
 Tablet browser (Vite + React PWA, :5173)
   │  WebRTC offer/answer: POST /api/offer        RTVI messages (both ways, over the WebRTC data channel)
   ▼
 Bot server (FastAPI + Pipecat, :7860)
   Pipeline:
   transport.in → STT (Deepgram Nova-3) → AttentionGate → FastPathRouter → user context
                → LLM (Claude Haiku 5.5, tools) → TTS (Deepgram Aura-2 | Cartesia) → transport.out → assistant context
   Side services (per kitchen session, survive reconnects):
     RecipeSession (state machine) · TimerService (asyncio) · RTVI event publisher
   REST: /api/recipes (library), /api/recipes/import (URL → Recipe), /api/offer (WebRTC signaling)
```

### Session continuity

The browser keeps a `kitchen_id` in localStorage. `RecipeSession` and `TimerService` live in a process-level registry keyed by `kitchen_id`, with a 6-hour TTL. If the WebRTC connection drops (tablet sleeps, Wi-Fi blips), the new pipeline reattaches to the same recipe position and running timers.

## 4. Repository layout

```
kitchen-companion/
├─ pyproject.toml            # uv, Python 3.12
├─ .env.example
├─ docker-compose.yml        # bot + web
├─ src/kitchen_companion/
│  ├─ config.py              # pydantic-settings; startup check lists missing keys
│  ├─ server.py              # FastAPI: signaling, recipe REST, kitchen registry
│  ├─ bot.py                 # builds and runs the Pipecat pipeline for one connection
│  ├─ prompts.py
│  ├─ tools.py               # LLM tool schemas + handlers bound to RecipeSession/TimerService
│  ├─ events.py              # RTVI server-message helpers (recipe state, timers, heard/overheard, latency)
│  ├─ pipeline/
│  │  ├─ attention.py        # AttentionGate FrameProcessor
│  │  ├─ fast_path.py        # intent parser (pure) + FastPathRouter FrameProcessor
│  │  └─ speakable.py        # kitchen-aware TTS text normalizer
│  ├─ timers.py              # TimerService (clock-injectable)
│  └─ recipes/
│     ├─ model.py            # Recipe, Ingredient, Step (pydantic)
│     ├─ state.py            # RecipeSession state machine
│     ├─ units.py            # conversion + friendly fractions
│     ├─ ingredients.py      # ingredient line parser ("1 1/2 cups flour, sifted")
│     ├─ importer.py         # URL → JSON-LD → Recipe
│     └─ library/*.json      # 6 bundled recipes
├─ tests/
│  ├─ unit/
│  ├─ pipeline/              # Pipecat frame-level tests, no keys
│  └─ evals/                 # needs ANTHROPIC_API_KEY; marked `eval`
└─ web/                      # Vite + React + TypeScript + @pipecat-ai/client-react
```

## 5. Components

### 5.1 Recipe model and state (`recipes/model.py`, `recipes/state.py`)

**`Recipe`:**
- `id`, `title`, `servings`, `total_time_min?`, `source_url?`
- `ingredients[]`: each an `Ingredient{qty: Fraction|None, unit: str|None, name, note?, raw}`
- `steps[]`: each a `Step{index, text, timer_minutes?, ingredient_refs[]}`

**`RecipeSession`:**
- **Loading:** `load(recipe)`.
- **Navigation:** `next()`, `prev()`, `goto(n)`, `repeat()`, `current()` and `progress()`. Navigation is clamped at both ends with speakable edge messages: "That was the last step — enjoy!" and "We're at the first step."
- **Scaling:** `scale_to(servings)` stores a factor; quantities are scaled on read, never mutated.
- **Lookup:** `ingredient(name)` does a fuzzy match (normalized tokens, singular/plural) and returns the scaled quantity in speakable form. When the match is ambiguous it returns the candidates.
- **Timer offers:** `pending_timer_offer` is set when the current step has `timer_minutes`. A "yes" accepts it.

### 5.2 Units (`recipes/units.py`)

- **Volume:** tsp, tbsp, cup, ml, l, fl oz.
- **Mass:** g, kg, oz, lb.
- **Temperature:** °F ↔ °C.
- **Friendly output:** rounds to kitchen-friendly fractions (⅛ steps for cups and spoons; whole grams; nearest 5 °F or °C) and says them aloud: "one and a half cups", "a quarter teaspoon".
- **Cross-type requests:** cup → gram needs a density, so it returns a clear "can't convert" result unless the ingredient is in a small density table (flour, sugar, butter, water, milk, rice).

### 5.3 Ingredient line parser (`recipes/ingredients.py`)

Handles:
- whole numbers, decimals, mixed fractions ("1 1/2") and unicode fractions ("½", "1½")
- ranges ("2-3", which keeps the low and high values)
- unit aliases ("Tbsp", "tablespoons", "T")
- parenthetical notes ("(about 2 cloves)") and trailing prep notes after a comma

Lines that can't be parsed keep `raw` and `qty=None`, so nothing is ever dropped.

### 5.4 Importer (`recipes/importer.py`)

- **Fetching:** `https` or `http` URLs only. Before fetching, it resolves the host and refuses private, loopback and link-local addresses (an SSRF guard, because the server fetches user-supplied URLs). Responses are capped at 10 s and 3 MB.
- **Finding the recipe:** parses every `<script type="application/ld+json">` block and finds the `@type: Recipe` object. That object may be top-level, in an array, or inside `@graph`, and `@type` may itself be a list.
- **Mapping:**
  - `recipeIngredient[]` is parsed into ingredients.
  - `recipeInstructions` may be a string, `HowToStep[]`, or `HowToSection[]` containing steps. All forms are flattened into numbered steps.
  - `recipeYield` becomes servings (the first integer found; defaults to 4).
  - `totalTime` is ISO 8601 and becomes minutes.
- **Timer hints:** a regex detects durations in step text ("simmer for 8–10 minutes" becomes 8).
- **No recipe found:** raises `RecipeNotFound`. The API maps it to a friendly 422 response.

### 5.5 Timer service (`timers.py`)

- **Operations:** `start(label, minutes)`, `cancel(label|id)`, `list()`, `remaining(label)`, `acknowledge()`.
- **Clock injection:** the clock and sleeper are injectable, so tests run instantly.
- **Firing:** when a timer fires, the service calls a `on_due(timer)` callback that the bot provides. The bot defers the announcement while the user is speaking (between `UserStartedSpeaking` and `UserStoppedSpeaking`), then pushes a `TTSSpeakFrame` such as: "Your onions timer is done — that was for step 4. Next up: add the garlic." It also opens the attention window.
- **Reminders:** an unacknowledged timer repeats its reminder every 60 s, up to 3 times. "Got it", "thanks", "okay" or "stop" acknowledge it.
- **Labels:** a timer without a label is named after the current step's main action, falling back to "timer 1", "timer 2" and so on.

### 5.6 Attention gate (`pipeline/attention.py`)

A `FrameProcessor` placed after STT. It passes a final `TranscriptionFrame` downstream only while **engaged**:

- **Getting engaged:**
  - The transcript contains the wake phrase. It is configurable, defaulting to "chef" with variants like "hey chef" and "okay chef". The wake phrase is stripped before passing the transcript on.
  - It is within `followup_window_s` (8 s) after the bot finished speaking or after a timer announcement.
  - The UI sent an `engage` RTVI message (the big tap target). That engages for one utterance.
- **Always passed:** "stop", "quiet" and "wait" while the bot is speaking.
- **When not engaged:** the frame is dropped downstream, and an `overheard` RTVI event goes to the UI, which shows the line greyed out.
- **Interruptions:** the bot is only interrupted by an *engaged* utterance of at least 2 words, or by a stop word. Kitchen noise and side conversations don't cut it off.
- **Testability:** the gate's decision logic is a pure function `decide(text, now, last_bot_speech_end, engaged_flag)`, unit-tested with a fake clock.

### 5.7 Fast-path router (`pipeline/fast_path.py`)

**Intent parser:** `parse(text) -> Intent | None` is pure and table-tested.

| Intent | Example phrasings |
|---|---|
| `next` | next, next step, what's next, done, okay next |
| `prev` | back, previous, go back |
| `repeat` | repeat, say that again, what was that |
| `goto(n)` | step three, go to step 3 |
| `stop` | stop, quiet, pause |
| `timer_start(minutes, label?)` | set a timer for 8 minutes for the onions; spoken numbers ("eight", "a minute and a half") are supported |
| `timer_cancel(label?)` | cancel the onion timer |
| `timer_query(label?)` | how long left, how much time on the onions |
| `yes` / `no` | answers a pending timer offer |
| `ack` | got it, thanks, okay (acknowledges a timer) |

**`FastPathRouter`** is a `FrameProcessor` placed after the attention gate. On a matched intent it:
1. performs the action on `RecipeSession` or `TimerService`;
2. pushes a `TTSSpeakFrame` with templated, speakable text;
3. appends the user/assistant exchange to the shared LLM context, so Claude stays aware of it;
4. emits RTVI state updates and a latency event marked `path: fast`.

Unmatched utterances pass through to the LLM.

**Degraded mode:** if the LLM is failing, fast-path commands keep working.

### 5.8 LLM and tools (`prompts.py`, `tools.py`)

- **Model:** Claude Haiku 5.5. There is no fallback model; failures produce a spoken "Sorry, I lost my train of thought — try that again?"
- **System prompt:**
  - A friendly, calm sous-chef. Replies of 1–2 sentences, speakable, no lists.
  - Quantities and timers *always* come from tools. It never guesses amounts.
  - The current recipe title, step and scale factor are injected into context on every turn.

| Tool | Behavior |
|---|---|
| `search_recipes(query)` | Searches the library by title or ingredients (token overlap). Returns the top 3. |
| `load_recipe(recipe_id)` | Loads a recipe and updates the STT keyterms. |
| `get_ingredient(name)` | Returns the scaled quantity, or the candidates if ambiguous. |
| `scale_recipe(servings)` | Sets the scale factor and returns a summary. |
| `convert_units(quantity, from_unit, to_unit, ingredient?)` | Converts using `units.py`. |
| `go_to_step(step)` | Accepts a number, "next", "prev" or "repeat". |
| `set_timer(minutes, label?)` | Starts a timer. |
| `cancel_timer(label?)` | Cancels a timer. |
| `list_timers()` | Lists running timers. |

Substitutions ("what can I use instead of buttermilk?") are answered from model knowledge, with no tool call.

### 5.9 Speakable text (`pipeline/speakable.py`)

Normalizes text before TTS:
- "1 1/2 cups" → "one and a half cups"
- "½ tsp" → "half a teaspoon"
- "350°F" → "three hundred fifty degrees Fahrenheit"
- "8-10 min" → "eight to ten minutes"
- "tbsp" → "tablespoons"
- strips markdown

### 5.10 STT, TTS, turn-taking

- **STT:** Deepgram Nova-3 with `smart_format`, and keyterms = the loaded recipe's ingredient names plus the wake phrase. On recipe load, the STT settings update; if live updates aren't supported, the STT reconnects.
- **TTS:** Deepgram Aura-2 by default, or Cartesia when `TTS_PROVIDER=cartesia`. A warm voice at a slightly slower rate.
- **Turn-taking:** Silero VAD with short stop time, plus Pipecat's local smart-turn analyzer so "set a timer for… um… ten minutes" isn't cut off early. The kitchen favors speed over patience.

### 5.11 Server (`server.py`)

| Endpoint | Purpose |
|---|---|
| `POST /api/offer` | SmallWebRTC signaling. Body carries the SDP and `kitchen_id`. Starts a bot pipeline for the connection, attached to that kitchen's `RecipeSession` and `TimerService`. |
| `GET /api/recipes` | Library list. |
| `GET /api/recipes/{id}` | One recipe. |
| `POST /api/recipes/import {url}` | Imports a recipe and returns it, adding it to an in-memory library for the process lifetime. |
| `GET /api/health` | Health check. |

### 5.12 Web (`web/`, Vite + React PWA)

**Screens:**
- **Recipe picker:** library cards plus an "Import from URL" field.
- **Cook mode:**
  - the current step in very large type, with a step progress strip
  - a scaled ingredient checklist (tap to tick off)
  - a timer row with large countdowns: amber under 1 minute, flashing when due
  - a giant "Hey Chef" tap target
  - a status orb (listening, thinking, speaking, idle)
  - a transcript drawer showing **heard** lines in full contrast and **overheard** lines greyed, with a latency chip on each reply tagged `fast` or `llm`, so the speed difference is visible

**Platform:**
- The Screen Wake Lock API keeps the screen on, re-acquired on visibility change.
- A web manifest makes it installable.
- Dark, high-contrast theme by default; works in landscape and portrait.

**State:** driven by RTVI server messages: `recipe_state`, `timers`, `heard`, `overheard` and `latency`. Timer countdowns tick locally from `ends_at`.

**Client actions:** UI actions go to the bot as RTVI client messages, and the server applies them to the same `RecipeSession` the voice path uses:
- `load_recipe{id}`: picking a recipe card
- `goto_step{n}`: tapping a step
- `engage`: the big button
- `ack_timer`

Touch and voice therefore always agree.

## 6. Data flow examples

**"Chef, next."**
1. STT final arrives as "Chef, next."
2. The gate is engaged by the wake phrase and passes "next".
3. The fast path does `next` and pushes "Step 4: melt three tablespoons of butter over medium heat. Want an eight-minute timer?"
4. TTS streams, and the UI gets `recipe_state` plus a `latency{path: fast}` event.
5. The LLM is not called.

**"Hmm, how much garlic again?"** (said 5 s after the bot spoke)
1. The gate is within the follow-up window and passes the utterance.
2. The fast path finds no match.
3. The LLM calls `get_ingredient("garlic")`, which returns "two cloves".
4. The LLM says "Two cloves, minced," and the UI gets `latency{path: llm}`.

**Two people chatting: "did you call your mom back?"**
1. The gate is not engaged and drops the utterance.
2. The UI shows it as overheard.

**Timer fires while the user is talking**
1. The service waits until the user stops speaking, then announces the timer.
2. The attention window opens.
3. "Got it" acknowledges it; otherwise it reminds again in 60 s.

## 7. Error handling

| Failure | Behavior |
|---|---|
| Missing keys | The server refuses to start and names the missing variables. |
| LLM error or timeout (8 s) | A spoken apology; fast-path commands keep working. |
| STT disconnect | Pipecat reconnect; the UI shows "reconnecting". |
| WebRTC drop | The client auto-reconnects with the same `kitchen_id`, and recipe and timers resume. |
| Import fails (no JSON-LD, blocked host, timeout, too big) | 422 with a human message: "Couldn't find a recipe on that page." |
| Ambiguous ingredient | "Do you mean the butter for the sauce or for the topping?" |
| Unit conversion impossible | "I can't convert cups of spinach to grams reliably — roughly a handful per cup." |

## 8. Testing

**Unit tests** (`tests/unit`, no keys, run in CI on every push):
- `units`: conversions, rounding, speakable fractions, cross-type with density, impossible cases.
- `ingredients`: a table of about 30 real-world lines.
- `importer`: JSON-LD fixtures covering top-level, `@graph`, list `@type`, `HowToSection`, string instructions, and a missing recipe; the SSRF guard with mocked DNS.
- `state`: navigation bounds, scaling, fuzzy ingredient lookup, timer offers.
- `timers`: fake clock; deferral while the user speaks; reminders capped at 3; acknowledgement.
- `attention.decide`: wake variants, follow-up window edges, stop words, engage flag.
- `fast_path.parse`: about 60 phrasings, including negatives that must *not* match (e.g. "next time I'll use less salt").
- `speakable`: a table of inputs to expected outputs.

**Pipeline tests** (`tests/pipeline`, no keys). Pipecat's frame test utilities feed frames through the gate and router with mocked LLM and TTS:
- An engaged "next" yields a `TTSSpeakFrame` and nothing reaches the LLM.
- An overheard utterance yields no downstream frames and an `overheard` event.
- An unmatched engaged utterance reaches the LLM aggregator.

**Tool-call evals** (`tests/evals`, need `ANTHROPIC_API_KEY`, `pytest -m eval`). Each runs Claude Haiku 5.5 with the real system prompt and tool schemas on scripted utterances:
- "how much butter do I need" → `get_ingredient("butter")`
- "make it for eight people" → `scale_recipe(8)`
- "convert that to grams" (after butter) → `convert_units(..., "g", ingredient="butter")`
- "what can I use instead of buttermilk" → no tool call; ≤ 2 sentences; no markdown (judge plus regex)
- "set a timer for the pasta, eleven minutes" → `set_timer(11, "pasta")`

**Web:** `tsc --noEmit` and `vite build`.

## 9. Configuration (`.env.example`)

```
ANTHROPIC_API_KEY=
DEEPGRAM_API_KEY=
CARTESIA_API_KEY=          # optional
TTS_PROVIDER=deepgram      # deepgram | cartesia
LLM_MODEL=claude-haiku-5-5
WAKE_PHRASE=chef
FOLLOWUP_WINDOW_S=8
HOST=0.0.0.0
PORT=7860
```

## 10. Running

- **Everything in Docker:** `docker compose up`. This runs the bot and web services; there is no media server.
- **Development:** `uv run kitchen-server` and `npm run dev` in `web/`.
- **On a real tablet:** browsers only allow microphone access over HTTPS or on localhost. The README documents using the dev machine's browser, or a tunnel or self-signed certificate for a tablet on the LAN.
- **CI:** one GitHub Actions job, filtered to this folder, runs the unit and pipeline tests, a lint (ruff), and the web build. A second job runs evals when the `ANTHROPIC_API_KEY` secret is present.

## 11. Decisions

- The wake phrase is detected from the transcript, not by an on-device wake-word model. It's simpler and costs some STT minutes, which is acceptable for a demo; an on-device detector is a documented upgrade.
- The fast path is placed *before* the LLM, and its exchanges are written into the LLM context, so the conversation stays coherent.
- Recipe and timer state are server-side and keyed by `kitchen_id`, so the state survives reconnects. The UI is a view of that state, never its source of truth.
- No MCP in this project. The tools are tightly bound to live session state; MCP is showcased in the Interview Coach.
