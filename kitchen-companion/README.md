# Kitchen Companion

A hands-free cooking assistant for a tablet propped up on the counter. It walks you through a
recipe step by step, answers "how much butter again?", scales and converts quantities, and runs
timers that speak up on their own. Say "Chef, next" with floury hands and the next step comes up
on screen and out of the speaker.

It's built on [Pipecat](https://github.com/pipecat-ai/pipecat) with peer-to-peer SmallWebRTC,
Deepgram for speech, and Claude Haiku 5.5 for the questions that need a model. Its sibling project,
[`../interview-coach`](../interview-coach), is built on LiveKit instead; the two are a deliberate
pair.

## Why it's built this way

A kitchen is a hard place for a voice agent: it's noisy, other people talk, most of what you say is
a two-word command, and the numbers have to be right. Each part of the design answers one of those.

| What the kitchen needs | What this project does |
|---|---|
| One device, one bot, no rooms | Pipecat with SmallWebRTC: the browser talks straight to the bot server, no media server to run |
| A noisy, shared room | An attention gate that only passes speech addressed to Chef, and a two-word threshold before the bot can be interrupted |
| Most utterances are tiny commands | A fast path answers "next", "back", "repeat", "go to step 3" and timer commands from code, with no LLM call |
| Hard numbers | Recipe state, scaling and unit conversion in deterministic, table-tested code; the model is told never to guess |
| Things happen on a clock | A timer service that speaks up unprompted, waits for a quiet moment, and reminds until acknowledged |
| Ingredient names are easy to mishear | Deepgram Nova-3 keyterms come from the loaded recipe |
| Short, quick answers | Claude Haiku 5.5 at low effort |
| A tablet on a counter | A Vite + React PWA with a screen wake lock and type you can read from a metre away |
| Recipes live on the web | Import by URL from the page's schema.org `Recipe` JSON-LD, behind an SSRF guard |

## The pipeline

```
Tablet browser (Vite + React PWA)
  │  POST /api/offer (WebRTC offer + kitchen_id)        RTVI messages both ways over the data channel
  ▼
Bot server (FastAPI + Pipecat, :7860)
  transport.in → Deepgram STT → AttentionGate → FastPathRouter → user aggregator → StateNoteInjector
               → Claude Haiku 5.5 (9 tools) → TTS (KitchenTextFilter) → transport.out → assistant aggregator

  Per kitchen, surviving reconnects:  RecipeSession · TimerService · queued timer announcements
```

- **AttentionGate** (`pipeline/attention.py`) drops speech that isn't addressed to the bot.
- **FastPathRouter** (`pipeline/fast_path.py`) answers matched commands from code and writes the
  exchange into the LLM context, so Claude still knows the cook moved to step 4.
- **StateNoteInjector** (`pipeline/state_note.py`) appends `[kitchen state: recipe 'Tomato Soup',
  step 4 of 7, scaled for 4 servings]` to each user message the LLM sees.
- **KitchenTextFilter** (`pipeline/speakable.py`) turns "1 1/2 cups" into "one and a half cups"
  and "350°F" into "three hundred fifty degrees Fahrenheit" before TTS.
- **Tools** (`tools.py`): `search_recipes`, `load_recipe`, `get_ingredient`, `scale_recipe`,
  `convert_units`, `go_to_step`, `set_timer`, `cancel_timer`, `list_timers`.

The browser keeps a `kitchen_id` in localStorage. Recipe position and timers live in a server-side
registry under that id for six hours, so when the tablet sleeps or the Wi-Fi blips, the new
connection picks up the same step and the same running timers. A timer that comes due while nobody
is connected announces itself as soon as the tablet reconnects.

## The attention gate and the fast path

Chef only answers when it's addressed:

- the line starts with the wake phrase ("Chef, next", "hey chef, how much garlic") — "pass me the
  chef's knife" doesn't count;
- it comes within 8 seconds of Chef finishing a sentence (so follow-ups don't need "Chef" again);
- the big **Hey Chef** button was tapped;
- or it's a bare "stop", "wait", "quiet" or "hold on" while Chef is talking.

Everything else is overheard: it never reaches the model, and the transcript drawer shows it greyed
out. Room noise can't cut Chef off either: there's no voice-activity trigger, and while Chef is
talking it takes an addressed utterance of at least two words (or a stop word) to interrupt.

Addressed lines then hit the fast path. "Next", "go back", "step three", "set a timer for eight
minutes for the onions", "how long left on the pasta", "cancel the timer", and "yes" to a timer
offer are all handled in code. Anything else, like "how much butter do I need?", goes to Claude,
which answers from the tools.

Open the transcript drawer while cooking and each reply carries a chip with how long it took from
the end of your speech to Chef's first audio, and which path answered: `fast · 280 ms` for code,
`llm · 1.1 s` for the model.

## Quick start with Docker

```bash
cp .env.example .env    # then fill in ANTHROPIC_API_KEY and DEEPGRAM_API_KEY
docker compose up --build
```

Open <http://localhost:7860> in a browser on the same machine and allow the microphone.

The image builds the tablet app and serves it from the bot server, so there's one container and no
media server. WebRTC audio, though, flows over UDP between the browser and the container on ports
the container picks at random. That works when the browser runs on the Docker host (Linux), but
with Docker Desktop or a tablet on the LAN the container's addresses usually aren't reachable. For
those, run the bot natively (below), or on Linux add `network_mode: host` to the service.

## Dev setup

Python 3.12 with [uv](https://docs.astral.sh/uv/), and Node 24.

```bash
uv sync
uv run kitchen-server            # bot + REST on :7860
```

```bash
cd web
npm install
npm run dev                      # tablet app on :5173, proxying /api to :7860
```

Open <http://localhost:5173>. The server refuses to start without its keys and names the missing
ones.

## Using it on a real tablet

Browsers only allow the microphone on `https://` pages or on `localhost`. On a tablet that's on the
same Wi-Fi as your dev machine, either:

- put an HTTPS tunnel in front of the web app (for example `cloudflared tunnel --url
  http://localhost:5173` or `ngrok http 5173`) and open the tunnel's URL on the tablet; the WebRTC
  audio itself still flows directly over the LAN; or
- serve the Vite dev server with a self-signed certificate and accept the warning on the tablet.

Add it to the home screen to install it as an app. The screen stays awake while a recipe is open
(Screen Wake Lock, re-acquired whenever the page becomes visible again).

## Keys

| Variable | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | Claude Haiku 5.5 (questions, tools) and the evals |
| `DEEPGRAM_API_KEY` | Speech-to-text (Nova-3) and the default voice (Aura-2) |
| `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID` | Only with `TTS_PROVIDER=cartesia` |

The other settings in `.env.example` (`LLM_MODEL`, `WAKE_PHRASE`, `FOLLOWUP_WINDOW_S`, `HOST`, `PORT`)
have working defaults.

## Tests and evals

```bash
uv run ruff check
uv run pytest                    # unit + pipeline tests, no keys needed
uv run pytest -m eval            # tool-call evals against Claude Haiku 5.5; skipped without ANTHROPIC_API_KEY
cd web && npm run typecheck && npm run build
```

- **Unit tests** cover units and spoken fractions, about 40 real ingredient lines, the JSON-LD
  importer and its SSRF guard (private, loopback, link-local and mapped addresses, redirects to
  private hosts, the 3 MB cap), the recipe state machine, timers on a fake clock, the attention
  decision, about 80 fast-path phrasings including ones that must not match ("next time I'll use
  less salt"), the speakable filter, tools, the registry and the REST API.
- **Pipeline tests** push real Pipecat frames through the gate and router: an addressed "next"
  becomes speech with no LLM call, an overheard line produces nothing, an unmatched question
  reaches the LLM aggregator.
- **Evals** run the real system prompt and tool schemas on scripted utterances: "how much butter do
  I need" calls `get_ingredient`, "make it for eight people" calls `scale_recipe(8)`, "convert that
  to grams" after butter calls `convert_units`, a substitution question uses no tool and stays
  within two plain sentences, and "set a timer for the pasta, eleven minutes" calls `set_timer`.

CI (`.github/workflows/kitchen-companion.yml`) runs lint, tests and the web build on every change to
this folder, and the evals when the repository has an `ANTHROPIC_API_KEY` secret.

## Known limitations

- The wake phrase is found in the transcript, not by an on-device wake-word model. It's simple and
  costs some speech-to-text minutes; an on-device detector is the upgrade.
- One device per kitchen. A second tablet with the same `kitchen_id` takes over timer
  announcements from the first.
- The import SSRF guard checks every address a host resolves to before each request and each
  redirect, but the HTTP client resolves the name again when it connects, so a DNS-rebinding
  attacker could still race it. Pinning the connection to the checked address is the fix.
- Imported recipes live in memory until the server restarts.
- Live voice needs real keys and a microphone; the automated tests stop at the frame level.

## Deviations from plan

The plan (`docs/plans/2026-10-23-kitchen-companion.md`) was written against Pipecat 1.13.0 source.
Where the installed library or the spec called for a different choice, the smallest change that
keeps the spec's behaviour was made:

1. **Pipecat names.** `PipelineWorker` and `WorkerRunner` instead of `PipelineTask` and
   `PipelineRunner`, and `broadcast_interruption()` instead of
   `push_interruption_task_frame_and_wait()`: the plan's names are deprecated aliases in 1.13.
   TTS voices are set through `Settings(voice=...)` because the `voice`/`voice_id` constructor
   arguments are deprecated.
2. **Interruptions need two words.** The user turn starts with
   `MinWordsUserTurnStartStrategy(min_words=2)` rather than `TranscriptionUserTurnStartStrategy`,
   which interrupts on any transcript. That's what the spec's "only interrupted by an engaged
   utterance of at least two words, or by a stop word" requires. There is still no VAD start
   strategy.
3. **The state note moved.** `StateNoteInjector` sits after the user aggregator and annotates the
   context's latest user message, instead of rewriting the transcript before it. Otherwise the note
   would count toward the two-word interruption threshold.
4. **Thinking is turned off explicitly.** The plan said to set `effort="low"` and leave `thinking`
   unset so Pipecat would send its lowest setting, but Pipecat 1.13 only sends that default when
   *neither* is set. The bot therefore passes `thinking=ThinkingConfig(type="disabled")` alongside
   `effort="low"` (Pipecat's own lowest setting for Haiku 5.5), and the evals send the same.
   The first user turn in the context is also guaranteed: when the conversation opens with Chef
   speaking (a recipe picked by touch, a timer going off), `StateNoteInjector` puts a short
   placeholder user turn first, because the Messages API wants the first turn to be the user's.
5. **Deepgram keyterms.** Verified in `pipecat/services/deepgram/stt.py`: an
   `STTUpdateSettingsFrame` with new keyterms reconnects the Deepgram stream, so there is no
   rebuild-on-next-connection fallback.
6. **Timer announcements are queued per connection** and wait for both the user (voice activity or
   an open turn) and the bot to be quiet, up to 20 seconds, so the timer loop never blocks. The plan
   fed the gate from user-turn frames only, which miss conversation the gate overheard.
7. **Kitchen registry details.** `Kitchen.attach` is async (it replays announcements that came due
   while disconnected) and runs when the tablet's RTVI client reports ready, so replayed speech
   isn't sent before the peer can carry audio. Reminders skipped while nobody was connected aren't
   used up. A stale connection's `detach` doesn't unhook its replacement, and a connected kitchen is
   never pruned.
8. **Small additions.** `TimerService.list()` (used by the plan's own router test and listed in the
   spec), an injectable sleeper, `CARTESIA_VOICE_ID` (Cartesia has no default voice), `WEB_DIST`,
   a 3-second continuation window so a second speech-to-text final of the same addressed sentence
   isn't dropped, a 10-second expiry on the Hey Chef button, an 8-second LLM watchdog that also
   cancels a late answer, and `empty_user_turn=None` on the user aggregator: a turn whose words the
   fast path answered ends empty, and Pipecat's default would otherwise ask the LLM to respond.
9. **Wording.** "Three steps." and "Want an eight-minute timer?" read naturally where the plan's
   f-strings gave "three steps" mid-sentence and "a eight-minute"; default timer labels say
   "Your timer 1 is done", not "Your timer 1 timer is done".
