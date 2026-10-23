# Kitchen Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A hands-free cooking assistant on Pipecat with these properties:
- It only answers when addressed.
- It handles common commands instantly without an LLM.
- Its quantities and timers come from deterministic code.
- Its timers speak up on their own.
- It runs as a tablet-friendly PWA.

**Architecture:** One FastAPI process handles SmallWebRTC signaling and the recipe REST endpoints. Each WebRTC connection gets a Pipecat pipeline:

```
transport.in → Deepgram STT → AttentionGate → FastPathRouter → StateNoteInjector → user aggregator
             → Claude Haiku 5.5 (tools) → Deepgram TTS (KitchenTextFilter) → transport.out → assistant aggregator
```

Recipe state and timers live in a per-`kitchen_id` registry, so they survive reconnects. The pure logic (units, parsing, state, timers, intent, attention) has no I/O and is unit-tested without keys.

**Tech Stack:**
- Python 3.12 (uv)
- pipecat-ai 1.13.0 with the anthropic, deepgram, silero, cartesia, webrtc and runner extras (the local smart-turn v3 analyzer ships in the base package)
- FastAPI, uvicorn, httpx, pydantic-settings
- pytest + pytest-asyncio, ruff
- Vite 8 + React + TypeScript, @pipecat-ai/client-js 1.14.0, @pipecat-ai/client-react 1.9.0, @pipecat-ai/small-webrtc-transport 1.11.0

**Spec:** `kitchen-companion/docs/specs/2026-10-23-kitchen-companion-design.md`

## Global Constraints

**Model and Claude settings:**
- Model `claude-haiku-5-5`, exactly.
- Construct the LLM as `AnthropicLLMService(api_key=..., settings=AnthropicLLMService.Settings(model=settings.llm_model, effort="low"))`. Leave `thinking` unset; Pipecat then sends the lowest thinking setting.
- Never set `temperature`, `top_p` or `top_k`.
- Never pass a forced `tool_choice`.
- There is no server-side refusal fallback for Haiku 5.5. A refusal or error is spoken as `"Sorry, I lost my train of thought — try that again?"`.

**Pipecat 1.13 APIs:**
- Turn strategies go in `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)), user_turn_strategies=UserTurnStrategies(start=[TranscriptionUserTurnStartStrategy()], stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]))`.
- There is deliberately **no VAD start strategy**, so room noise never interrupts the bot. Only transcripts that pass the gate start a turn.
- Context: `LLMContext(messages=[{"role": "system", "content": SYSTEM_PROMPT}], tools=build_tools(...))`, wrapped in `LLMContextAggregatorPair(context, user_params=...)`.

**Speech services:**
- STT: `DeepgramSTTService(api_key=..., settings=DeepgramSTTService.Settings(model="nova-3", smart_format=True, keyterm=[...]))`.
- On recipe load, push `STTUpdateSettingsFrame(delta=DeepgramSTTService.Settings(keyterm=terms))`. If that frame doesn't apply keyterms live, log it and rebuild the STT service on the next connection instead. Verify against `pipecat/services/deepgram/stt.py` while implementing.
- TTS: `DeepgramTTSService(api_key=..., voice="aura-2-thalia-en", text_filters=[KitchenTextFilter()])`. With `TTS_PROVIDER=cartesia`, use `CartesiaTTSService` with the same filter.

**RTVI messages:**
- Server → client: `RTVIServerMessageFrame(data={"type": <kind>, ...})`, where the kind is one of `recipe_state`, `timers`, `heard`, `overheard`, `latency` or `error`.
- Client → server: `load_recipe{id}`, `goto_step{n}`, `engage`, `ack_timer`, handled through the RTVI processor's `on_client_message` event (`task.rtvi`).

**Values from the spec:**

| Setting | Value |
|---|---|
| wake phrase default | `chef` |
| follow-up window | 8.0 s |
| reminder interval | 60 s |
| maximum reminders | 3 (after the first announcement) |
| kitchen TTL | 6 h |
| import timeout | 10 s |
| import size cap | 3 MB |
| redirect hops | at most 3, each re-checked by the SSRF guard |
| LLM timeout | 8 s |
| server port | 7860 |
| web dev port | 5173 (proxying `/api` to 7860) |

**Other rules:**
- Units are US customary. 1 cup = 236.588 ml, 1 tbsp = 14.787 ml, 1 tsp = 4.929 ml, 1 fl oz = 29.574 ml, 1 oz = 28.3495 g, 1 lb = 453.592 g.
- Densities (g/ml): flour 0.53, sugar 0.85, butter 0.911, water 1.0, milk 1.03, rice 0.78.
- Unit tests and pipeline tests must pass with no API keys. Eval tests are marked `@pytest.mark.eval` and skipped without `ANTHROPIC_API_KEY`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The wake word appears but isn't addressing the bot** ("pass me the chef's knife", "the chef on TV said…"). The gate does not engage. Test: `test_wake_word_must_lead` (Task 9).
2. **A timer comes due while the bot is speaking, not just the user.** The announcement waits until both are quiet. Test: `test_announcement_waits_for_bot` (Task 6).
3. **Two timers come due in the same tick.** There is one callback containing both, spoken as one sentence ("Your pasta and garlic timers are done."). Tests: `test_simultaneous_timers_one_announcement` and `test_announcement_text_two_labels` (Task 6).
4. **"Cancel the timer" while two are running.** The bot asks which one instead of cancelling both. Tests: `test_cancel_ambiguous` (Task 6) and `test_router_cancel_ambiguous_asks` (Task 10).
5. **An imported recipe with no steps, or with lines it can't parse.** Navigation says "This recipe has no steps.", and ingredient lookup returns the raw line. Tests: `test_zero_steps_navigation` and `test_ingredient_without_qty_returns_raw` (Task 4).

---

### Task 1: Project scaffold and config

**Files:**
- Create: `kitchen-companion/pyproject.toml`, `kitchen-companion/.env.example`
- Create: `src/kitchen_companion/__init__.py`, `src/kitchen_companion/config.py`
- Create: `tests/conftest.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces:
  - `class Settings(BaseSettings)`: fields exactly as in spec §9 (lower-snake), with defaults `llm_model="claude-haiku-5-5"`, `wake_phrase="chef"`, `followup_window_s=8.0`, `port=7860` and `tts_provider="deepgram"`.
  - `REQUIRED = ("anthropic_api_key", "deepgram_api_key")`
  - `def missing_keys(settings, required) -> list[str]`
  - `def require(settings, required) -> None`: raises `SystemExit("Missing required environment variables: …")` with the names upper-cased.

- [ ] **Step 1: Write `pyproject.toml`** (`requires-python = ">=3.12,<3.13"`) and `.env.example` (verbatim from spec §9).
  - Script: `kitchen-server = "kitchen_companion.server:run"`.
  - Pytest: `asyncio_mode = "auto"`, an `eval` marker, `addopts = "-m 'not eval'"`.
- [ ] **Step 2: Write the failing tests:**
  - `test_defaults_match_spec`
  - `test_missing_keys_reports_empty`
  - `test_require_exits_with_upper_names`, which matches `"DEEPGRAM_API_KEY"`.
- [ ] **Step 3: Run** `cd kitchen-companion && uv sync && uv run pytest tests/unit/test_config.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement `config.py`.** Run again. Expected: 3 passed.
- [ ] **Step 5: Commit**: `feat(kitchen): scaffold project and config`.

### Task 2: Recipe model and units

**Files:**
- Create: `src/kitchen_companion/recipes/__init__.py`, `model.py`, `units.py`
- Test: `tests/unit/test_units.py`

**Interfaces:**
- Produces (`model.py`, pydantic, with `Fraction` stored as a `"n/d"` string through validators):
  - `class Ingredient: qty: Fraction | None; qty_max: Fraction | None = None; unit: str | None; name: str; note: str | None = None; raw: str`
  - `class Step: index: int; text: str; timer_minutes: int | None = None`
  - `class Recipe: id: str; title: str; servings: int = 4; total_time_min: int | None = None; source_url: str | None = None; ingredients: list[Ingredient]; steps: list[Step]`
- Produces (`units.py`):
  - `CANONICAL = {"tsp", "tbsp", "cup", "ml", "l", "floz", "g", "kg", "oz", "lb"}`
  - `COUNT_UNITS = {"clove", "can", "pinch", "slice", "sprig", "bunch", "stick", "package"}`
  - `def normalize_unit(token: str) -> str | None`. This mapping is case-sensitive: `"T"` → tbsp and `"t"` → tsp. Everything else is case-insensitive, and plurals and full names are accepted.
  - `class ConversionError(ValueError)`
  - `def convert(qty: Fraction, from_unit: str, to_unit: str, ingredient: str | None = None) -> Fraction`. Volume↔mass needs a density keyed by an ingredient substring; otherwise it raises `ConversionError`.
  - `def convert_temp(value: float, from_scale: Literal["F", "C"], to_scale: Literal["F", "C"]) -> int`: rounds to the nearest 5.
  - `def round_kitchen(qty: Fraction, unit: str | None) -> Fraction`: ⅛ steps for tsp, tbsp and cup; whole numbers for g, ml, oz and count units.
  - `def number_words(n: int) -> str`: covers 0–9999.
  - `def speak_quantity(qty: Fraction, unit: str | None) -> str`

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.parametrize("q,u,exp", [
    (F(3,2),"cup","one and a half cups"), (F(1,2),"tsp","half a teaspoon"), (F(1,4),"cup","a quarter cup"),
    (F(3,4),"cup","three quarters of a cup"), (F(1,3),"cup","a third of a cup"), (F(1,8),"tsp","an eighth of a teaspoon"),
    (F(1),"tbsp","one tablespoon"), (F(3),"tbsp","three tablespoons"), (F(2),None,"two"), (F(2),"clove","two cloves"),
    (F(9,4),"cup","two and a quarter cups"), (F(250),"g","two hundred fifty grams")])
def test_speak_quantity(q, u, exp): assert speak_quantity(q, u) == exp
def test_convert_volume(): assert round_kitchen(convert(F(1),"cup","ml"),"ml") == 237
def test_convert_butter_cup_to_grams(): assert round_kitchen(convert(F(1),"cup","g","unsalted butter"),"g") == 216  # 236.588*0.911
def test_convert_needs_density():
    with pytest.raises(ConversionError): convert(F(1),"cup","g","spinach")
def test_convert_temp(): assert (convert_temp(350,"F","C"), convert_temp(180,"C","F")) == (175, 355)
def test_normalize_unit_case(): assert (normalize_unit("T"), normalize_unit("t"), normalize_unit("Tablespoons")) == ("tbsp","tsp","tbsp")
def test_round_kitchen_eighths(): assert round_kitchen(F(1,3),"cup") == F(3,8)
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_units.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Expected: all pass.
- [ ] **Step 4: Commit**: `feat(kitchen): recipe model and unit conversion`.

### Task 3: Ingredient line parser

**Files:**
- Create: `src/kitchen_companion/recipes/ingredients.py`
- Test: `tests/unit/test_ingredients.py`

**Interfaces:**
- Consumes: `Ingredient`, `normalize_unit` and `COUNT_UNITS` (Task 2).
- Produces: `def parse_ingredient(line: str) -> Ingredient`. It never raises. An unparseable line gives `qty=None, unit=None, name=line.strip()` with `raw=line`.

- [ ] **Step 1: Write the failing parametrized test, `test_parse_ingredient`.** Use at least 30 rows, including these exact ones (qty, qty_max, unit, name, note):

| Input | qty | qty_max | unit | name | note |
|---|---|---|---|---|---|
| `"2 cups flour"` | 2 | – | cup | flour | – |
| `"1 1/2 cups whole milk"` | 3/2 | – | cup | whole milk | – |
| `"½ tsp salt"` | 1/2 | – | tsp | salt | – |
| `"1½ tbsp olive oil"` | 3/2 | – | tbsp | olive oil | – |
| `"2-3 cloves garlic, minced"` | 2 | 3 | clove | garlic | minced |
| `"3 Tbsp butter"` | 3 | – | tbsp | butter | – |
| `"1 T sugar"` | 1 | – | tbsp | sugar | – |
| `"1 t vanilla extract"` | 1 | – | tsp | vanilla extract | – |
| `"1 (14 oz) can diced tomatoes"` | 1 | – | can | diced tomatoes | 14 oz |
| `"0.5 lb ground beef"` | 1/2 | – | lb | ground beef | – |
| `"4 large eggs"` | 4 | – | None | large eggs | – |
| `"200g spaghetti"` | 200 | – | g | spaghetti | – |
| `"Salt and pepper to taste"` | None | – | None | Salt and pepper to taste | – |
| `"a pinch of nutmeg"` | 1 | – | pinch | nutmeg | – |

- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement.** A regex tokenizer handles the leading quantity (mixed, unicode, decimal, range), then the optional parenthetical note, then the unit, then `of`, then the name, with the note after the comma.
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(kitchen): ingredient line parser`.

### Task 4: RecipeSession state machine

**Files:**
- Create: `src/kitchen_companion/recipes/state.py`
- Test: `tests/unit/test_state.py`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces:
  - `@dataclass class IngredientAnswer: found: bool; text: str; candidates: list[str]`
  - `class RecipeSession`:
    - Attributes: `recipe: Recipe | None`, `index: int`, `scale: Fraction`, `pending_timer_offer: int | None`
    - `load(recipe: Recipe) -> str`: returns `f"Okay — {title}. {number_words(n)} steps. " + current()`.
    - `current() -> str`: returns `f"Step {number_words(i+1)}: {text}"`. If the step has `timer_minutes`, it appends `f" Want a {number_words(m)}-minute timer?"` and sets `pending_timer_offer`; otherwise it clears the offer.
    - `next() -> str`, `prev() -> str`, `goto(n: int) -> str` (1-based), `repeat() -> str`
    - `scale_to(servings: int) -> str`: returns `f"Scaled to {number_words(servings)} servings."`.
    - `ingredient(name: str) -> IngredientAnswer`
    - `timer_label() -> str | None`: the first word of the current step that is in `COOKING_VERBS` (`boil, simmer, bake, roast, fry, saute, cook, rest, chill, marinate, steam, toast, sear, proof, rise, knead, whisk`). Otherwise `f"step {i+1}"`; `None` with no recipe.
    - `next_step_text() -> str | None`
    - `snapshot() -> dict`: `{id, title, index, total, servings, steps: [text], ingredients: [{text, checked: False}]}`, with the ingredient text spoken-scaled.

**Exact messages:**

| Situation | Message |
|---|---|
| No recipe loaded | `"No recipe loaded yet — pick one on the screen or ask me to find one."` |
| Next at the last step | `"That was the last step — enjoy!"` |
| Back at the first step | `"We're at the first step. " + current()` |
| `goto` out of range | `f"This recipe has {number_words(n)} steps."` |
| Recipe with zero steps | `"This recipe has no steps."` |
| Ambiguous ingredient | `"Do you mean " + " or ".join(candidates) + "?"` |

**Ingredient matching:** lowercase, strip punctuation, and singularize (drop a trailing `es`/`s` on tokens longer than 3 characters). A match means every query token is in the ingredient name tokens. Quantities are scaled with `speak_quantity(round_kitchen(qty * scale, unit), unit) + " " + name`. With `qty=None`, return `raw`.

- [ ] **Step 1: Write the failing tests:**
  - `test_load_and_navigate`: next increments, prev decrements, goto(3)
  - `test_next_at_end_message`
  - `test_prev_at_start_message`
  - `test_goto_out_of_range`
  - `test_no_recipe_message`
  - `test_timer_offer_set_and_cleared`
  - `test_scale_changes_quantities`: a 4-serving recipe scaled to 8 makes "1 cup flour" → "two cups flour"
  - `test_ingredient_ambiguous`: two butter lines give `candidates` of length 2
  - `test_ingredient_plural_match`: "eggs" matches "large egg"
  - `test_zero_steps_navigation`
  - `test_ingredient_without_qty_returns_raw`
  - `test_timer_label_uses_verb`: "Simmer the sauce for 10 minutes" → `"simmer"`
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_state.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Expected: all pass.
- [ ] **Step 4: Commit**: `feat(kitchen): recipe session state machine`.

### Task 5: Recipe library, search and URL importer

**Files:**
- Create: `src/kitchen_companion/recipes/library.py`, `importer.py`, and `library/*.json` (6 recipes)
- Test: `tests/unit/test_library.py`, `tests/unit/test_importer.py`, `tests/fixtures/jsonld/*.html`

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces (`library.py`):
  - `class Library`:
    - `__init__(self, recipes: dict[str, Recipe])`
    - `@classmethod load_bundled(cls) -> Library`
    - `get(id) -> Recipe | None`
    - `all() -> list[Recipe]`
    - `add(recipe) -> None`
    - `search(query: str, limit: int = 3) -> list[Recipe]`: token overlap with title plus ingredient names, ties broken by title. Zero overlap returns nothing.
- Produces (`importer.py`):
  - `class RecipeNotFound(ValueError)`
  - `class ImportBlocked(ValueError)`
  - `def parse_iso_minutes(s: str | None) -> int | None`
  - `def timer_hint(step_text: str) -> int | None`: the first `N` or `N-M` (or `N to M`) followed by `minutes` / `mins` / `min` / `hour(s)` gives the low value in minutes. Seconds-only gives `None`.
  - `def extract_recipe(html: str, source_url: str) -> Recipe`: pure. It uses a stdlib `html.parser.HTMLParser` to collect `application/ld+json` scripts.
  - `async def import_recipe(url: str, *, transport: httpx.AsyncBaseTransport | None = None, resolve: Callable[[str], list[str]] = default_resolve) -> Recipe`
- **Bundled recipes:** garlic butter pasta, fluffy pancakes, chicken stir-fry, tomato soup, chocolate chip cookies, and a spinach & feta omelette. Each has 5–9 steps, at least one step with `timer_minutes`, and real quantities.

- [ ] **Step 1: Write the failing tests:**
  - `test_bundled_library_has_six_valid`
  - `test_search_eggs_spinach_finds_omelette` (first result)
  - `test_search_no_overlap_empty`
  - `test_parse_iso_minutes`: `"PT1H15M"` → 75, `"PT45M"` → 45, `None` → None
  - `test_timer_hint`: `"simmer for 8-10 minutes"` → 8, `"bake 1 hour"` → 60, `"stir for 30 seconds"` → None
  - `test_extract_top_level`, `test_extract_graph`, `test_extract_type_list`: `"@type": ["Recipe", "NewsArticle"]`
  - `test_extract_howtosection_flattens`: 2 sections × 2 steps = 4 numbered steps
  - `test_extract_string_instructions`
  - `test_extract_missing_raises`: `RecipeNotFound`
  - `test_import_blocks_private_ip`: `resolve` returns `["10.0.0.5"]`, giving `ImportBlocked`
  - `test_import_blocks_non_http`: `"file:///etc/passwd"` gives `ImportBlocked`
  - `test_import_redirect_to_private_blocked`: a MockTransport returns 302 to `http://internal/`, and resolve maps `internal` to `127.0.0.1`, giving `ImportBlocked`
  - `test_import_size_cap`: a 4 MB body gives `RecipeNotFound("page too large")`
  - `test_import_success` (MockTransport with a fixture HTML)
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_library.py tests/unit/test_importer.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Write the recipe JSON files first.
  - The SSRF guard uses `ipaddress.ip_address(a)` and checks `is_private or is_loopback or is_link_local or is_reserved or is_multicast or is_unspecified` for **every** resolved address.
  - Redirects are followed manually (`follow_redirects=False`), up to 3 hops, re-checking each one.
  - The body is streamed with a running byte count.
  - The id is `slugify(title) + "-" + sha1(url)[:6]`.
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(kitchen): recipe library, search, and safe URL importer`.

### Task 6: Timer service, announcement gate and announcement text

**Files:**
- Create: `src/kitchen_companion/timers.py`
- Test: `tests/unit/test_timers.py`

**Interfaces:**
- Produces:
  - `@dataclass class Timer: id: str; label: str; minutes: float; ends_at: float; state: Literal["running", "due", "acknowledged", "cancelled"] = "running"; reminders: int = 0; last_announced: float | None = None`
  - `@dataclass class CancelResult: cancelled: list[Timer]; ambiguous: list[str]`
  - `class TimerService`:
    - `__init__(self, on_due: Callable[[list[Timer], bool], Awaitable[None]], *, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time, reminder_interval: float = 60.0, max_reminders: int = 3)`. The callback's second argument is `is_reminder`.
    - `start(minutes: float, label: str | None = None) -> Timer`. When `label` is None it is `f"timer {n}"`. A label that clashes with a running timer gets `" 2"`, `" 3"`… appended.
    - `cancel(label: str | None = None) -> CancelResult`:
      - With no label and one running timer, cancels that timer.
      - With no label and more than one running, returns `ambiguous=[labels]` and cancels nothing.
      - Matching is a case-insensitive substring.
    - `remaining(label: str | None = None) -> list[tuple[Timer, float]]`: seconds left for running timers.
    - `acknowledge() -> list[Timer]`
    - `async tick() -> None`: collects every running timer whose `ends_at <= clock()`, marks them due, and calls `on_due(list, False)` **once**. Then, for due timers with `reminders < max_reminders` and `clock() - last_announced >= reminder_interval`, it calls `on_due(list, True)` once, incrementing `reminders`.
    - `async run() -> None`: loops `tick(); sleep(0.25)`.
    - `snapshot() -> list[dict]`: `{id, label, state, ends_at_epoch}`, where `ends_at_epoch = wall() + (ends_at − clock())`.
  - `class AnnouncementGate`:
    - `set_user_speaking(b: bool)`, `set_bot_speaking(b: bool)`
    - `async wait_clear(timeout: float | None = None) -> None`: returns once both are False.
  - `def announcement_text(labels: list[str], next_step: str | None, reminder: bool) -> str`:
    - one timer: `"Your {label} timer is done."`
    - two timers: `"Your {a} and {b} timers are done."`
    - three or more: comma-joined with "and"
    - reminder: `"Reminder: your {labels} timer(s) went off."`
    - appends `" Next up: {next_step}"` when `next_step` is set and it's not a reminder

- [ ] **Step 1: Write the failing tests** (fake clock = a mutable float; `on_due` records calls):

```python
async def test_fires_once_when_due(): t.start(1, "pasta"); clk.now = 59; await t.tick(); assert calls == []
    # then clk.now = 60 → calls == [(["pasta"], False)]; another tick at 61 → still one call
async def test_simultaneous_timers_one_announcement():  # Review Focus 3
    t.start(1, "pasta"); t.start(1, "garlic"); clk.now = 60; await t.tick(); assert calls == [(["pasta", "garlic"], False)]
async def test_reminders_capped(): ...  # due at 60, ticks at 120,180,240,300,360 → 3 reminder calls total, none after
async def test_acknowledge_stops_reminders(): ...
def test_cancel_ambiguous():  # Review Focus 4
    t.start(5, "pasta"); t.start(3, "sauce"); r = t.cancel(); assert r.cancelled == [] and r.ambiguous == ["pasta", "sauce"]
def test_default_and_duplicate_labels(): assert [t.start(1).label, t.start(1).label, t.start(1, "rice").label, t.start(1, "rice").label] == ["timer 1","timer 2","rice","rice 2"]
async def test_announcement_waits_for_bot():  # Review Focus 2
    g = AnnouncementGate(); g.set_bot_speaking(True); w = asyncio.create_task(g.wait_clear())
    await asyncio.sleep(0); assert not w.done(); g.set_bot_speaking(False); await asyncio.wait_for(w, 1)
def test_announcement_text_two_labels(): assert announcement_text(["pasta","garlic"], None, False) == "Your pasta and garlic timers are done."
def test_announcement_text_next_step(): assert announcement_text(["onions"], "add the garlic.", False) == "Your onions timer is done. Next up: add the garlic."
def test_snapshot_epoch(): ...  # wall=1000, clock=0, start(2) → ends_at_epoch == 1120
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_timers.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** (`AnnouncementGate` uses an `asyncio.Event`). Expected: all pass.
- [ ] **Step 4: Commit**: `feat(kitchen): timer service and announcement gate`.

### Task 7: Kitchen speakable filter

**Files:**
- Create: `src/kitchen_companion/pipeline/__init__.py`, `pipeline/speakable.py`
- Test: `tests/unit/test_speakable.py`

**Interfaces:**
- Consumes: `normalize_unit`, `speak_quantity` and `number_words` (Task 2).
- Produces:
  - `def normalize(text: str) -> str`
  - `class KitchenTextFilter(pipecat.utils.text.base_text_filter.BaseTextFilter)`. Its `async filter(self, text) -> str` returns `normalize(text)`. Implement the other abstract methods as no-ops.

- [ ] **Step 1: Write the failing parametrized test, `test_normalize`:**

| Input | Expected output |
|---|---|
| `"1 1/2 cups flour"` | `"one and a half cups flour"` |
| `"½ tsp salt"` | `"half a teaspoon salt"` |
| `"Bake at 350°F"` | `"Bake at three hundred fifty degrees Fahrenheit"` |
| `"180°C"` | `"one hundred eighty degrees Celsius"` |
| `"simmer 8-10 min"` | `"simmer eight to ten minutes"` |
| `"2 tbsp oil"` | `"two tablespoons oil"` |
| `"**Stir** well"` | `"Stir well"` |
| `"Step 3: whisk"` | `"Step three: whisk"` |
| `"1/4 cup"` | `"a quarter cup"` |

  Add `test_filter_async` for the filter class.
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement.** Expected: all pass.
- [ ] **Step 4: Commit**: `feat(kitchen): speakable text filter`.

### Task 8: Fast-path intent parser

**Files:**
- Create: `src/kitchen_companion/pipeline/fast_path.py` (the parser part only)
- Test: `tests/unit/test_fast_path_parse.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Intent: kind: Literal["next", "prev", "repeat", "goto", "stop", "timer_start", "timer_cancel", "timer_query", "yes", "no", "ack"]; n: int | None = None; minutes: float | None = None; label: str | None = None`
  - `def parse_duration_minutes(text: str) -> float | None`
  - `def parse(text: str) -> Intent | None`

**Rules:**
- Lowercase the text, strip punctuation, and strip leading or trailing politeness words (`please`, `okay`, `ok`, `alright`, `now`, `chef`).
- **Navigation, stop, yes/no and ack must be a full match** of a short command, so a sentence that merely contains "next" never matches.
- Timer intents may be longer, but must contain `timer` (or `how long`/`time left` for queries) and, for start, a parseable duration.
- Number words cover 1–90, "a", "an", "half", "a half" and "and a half".

- [ ] **Step 1: Write the failing table test** (at least 60 rows: about 45 must-match and 15 must-not-match), including these exact rows:

| Input | Expected |
|---|---|
| `"next"` | `next` |
| `"what's next"` | `next` |
| `"okay next please"` | `next` |
| `"I'm done"` | `next` |
| `"go back"` | `prev` |
| `"say that again"` | `repeat` |
| `"go to step 3"` | `goto(n=3)` |
| `"step five"` | `goto(5)` |
| `"stop"` | `stop` |
| `"hold on"` | `stop` |
| `"set a timer for 8 minutes"` | `timer_start(8)` |
| `"set a timer for eight minutes for the onions"` | `timer_start(8, "onions")` |
| `"start a timer for a minute and a half"` | `timer_start(1.5)` |
| `"half an hour timer"` | `timer_start(30)` |
| `"set a timer for 1 hour 15 minutes"` | `timer_start(75)` |
| `"set a timer for 90 seconds"` | `timer_start(1.5)` |
| `"cancel the onion timer"` | `timer_cancel(label="onion")` |
| `"cancel the timer"` | `timer_cancel(None)` |
| `"how long left on the pasta"` | `timer_query("pasta")` |
| `"how much time is left"` | `timer_query(None)` |
| `"yes please"` | `yes` |
| `"no thanks"` | `no` |
| `"got it"` | `ack` |
| `"thanks"` | `ack` |
| `"next time I'll use less salt"` | `None` |
| `"I'll go back to the store later"` | `None` |
| `"can you repeat the part about the oven"` | `None` |
| `"how much butter do I need"` | `None` |
| `"set the table"` | `None` |
| `"what can I make with eggs"` | `None` |
| `"stop adding salt when"` | `None` |

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_fast_path_parse.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** with anchored regexes compiled once. Expected: all pass.
- [ ] **Step 4: Commit**: `feat(kitchen): fast-path intent parser`.

### Task 9: Attention decision

**Files:**
- Create: `src/kitchen_companion/pipeline/attention.py` (the decision part only)
- Test: `tests/unit/test_attention.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AttentionConfig: wake_phrase: str = "chef"; followup_window_s: float = 8.0`
  - `@dataclass(frozen=True) class Decision: engaged: bool; text: str; reason: Literal["wake", "followup", "button", "stop_word", "not_addressed", "empty"]`
  - `STOP_WORDS = ("stop", "wait", "quiet", "be quiet", "hold on", "pause")`
  - `def decide(text: str, *, now: float, window_open_until: float, button_armed: bool, bot_speaking: bool, cfg: AttentionConfig) -> Decision`

**Rules, applied in order:**
1. Empty or whitespace text → `empty`.
2. Leading wake → engaged `wake`. The pattern is `^\s*(?:(hey|hi|ok|okay|yo)[\s,]+)?<wake>(?!['’]s)\b[\s,.!?]*`, case-insensitive. Strip the match. The remaining text may be `""`.
3. `button_armed` → `button`, with the text unchanged.
4. `now <= window_open_until` → `followup`.
5. `bot_speaking` and the text fully matches a stop word (optionally with "please") → `stop_word`.
6. Otherwise `not_addressed`, with the text unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_wake_variants`: "Chef, next" → engaged, `"next"`; "hey chef what's next" → `"what's next"`; "OK Chef." → `""`
  - `test_wake_word_must_lead` (Review Focus 1): "pass me the chef's knife" → not engaged; "the chef said add salt" → not engaged; "chef's kiss" → not engaged
  - `test_followup_window_edges`: `now == window_open_until` → engaged; `now` 0.01 s later → not engaged
  - `test_button_engages_once_text_kept`
  - `test_stop_word_only_while_bot_speaking`
  - `test_overheard`: "did you call your mom back" → `not_addressed`
  - `test_custom_wake_phrase`: `cfg.wake_phrase = "sous"`, "sous, next" → engaged
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_attention.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Expected: all pass.
- [ ] **Step 4: Commit**: `feat(kitchen): attention decision logic`.

### Task 10: Pipeline processors, events and latency

**Files:**
- Modify: `pipeline/attention.py` (add the processor) and `pipeline/fast_path.py` (add the router)
- Create: `src/kitchen_companion/events.py`, `pipeline/state_note.py`
- Test: `tests/pipeline/test_gate_router.py`, `tests/unit/test_latency_clock.py`, `tests/fakes.py`

**Interfaces:**
- Consumes:
  - `decide` and `AttentionConfig` (Task 9)
  - `parse` and `Intent` (Task 8)
  - `RecipeSession` (Task 4)
  - `TimerService` and `announcement_text` (Task 6)
- Produces (`events.py`):
  - `class EventSink(Protocol)`, with these async methods:
    - `heard(text: str)`
    - `overheard(text: str)`
    - `latency(path: Literal["fast", "llm"], ms: int)`
    - `recipe_state(snapshot: dict)`
    - `timers(snapshot: list[dict])`
    - `error(message: str)`
  - `class RTVIEventSink`: `__init__(self, push: Callable[[Frame], Awaitable[None]])`. Each method pushes `RTVIServerMessageFrame(data={"type": <method name>, ...fields})`.
  - `class TurnPath`: a mutable holder whose `value` is `"fast"` or `"llm"`; the default is `"llm"`.
  - `class LatencyClock`:
    - `user_stopped(t: float)`
    - `bot_started(t: float) -> int | None`: returns ms since the last `user_stopped`, once per user turn.
  - `class LatencyObserver(BaseObserver)`: `__init__(self, clock: LatencyClock, path: TurnPath, sink: EventSink)`. `on_push_frame` maps `VADUserStoppedSpeakingFrame` to `user_stopped` and `BotStartedSpeakingFrame` to `bot_started`; when that returns ms, it calls `sink.latency(path.value, ms)` and resets the path to `"llm"`.
- Produces (`AttentionGate(FrameProcessor)`):
  - `__init__(self, cfg: AttentionConfig, sink: EventSink, clock: Callable[[], float] = time.monotonic)`
  - `arm_button()`
  - `open_window(seconds: float | None = None)`
  - `bot_speaking: bool`
- **`AttentionGate` behavior:**
  - It tracks `BotStartedSpeakingFrame` and `BotStoppedSpeakingFrame` from either direction. On stop it sets `window_open_until = clock() + cfg.followup_window_s`.
  - For a final `TranscriptionFrame`, it calls `decide`:
    - **Engaged** with text: push `TranscriptionFrame` with the stripped text and the same `user_id` and `timestamp`, and call `sink.heard`.
    - **Engaged** with empty text (bare wake): push `TTSSpeakFrame("Yes?")` and `open_window()`.
    - **Not engaged:** call `sink.overheard` and drop the frame.
  - `InterimTranscriptionFrame` passes only while the window is open or the button is armed.
  - Every other frame passes through in its own direction.
- Produces (`FastPathRouter(FrameProcessor)`): `__init__(self, recipe: RecipeSession, timers: TimerService, sink: EventSink, path: TurnPath)`.
- **`FastPathRouter` behavior:** for a final `TranscriptionFrame`, it handles the parsed intent as follows:

| Intent | Reply |
|---|---|
| `next` / `prev` / `repeat` / `goto` | the `RecipeSession` method's return value |
| `stop` | `await self.push_interruption_task_frame_and_wait()`, no reply |
| `timer_start` | `timers.start(minutes, label or recipe.timer_label())`; reply `f"{label} timer set for {speak}."`; `sink.timers(...)` |
| `timer_cancel` | `ambiguous` → `"Which timer — " + " or ".join(labels) + "?"`; none running → `"There's no timer running."`; otherwise `f"Cancelled the {label} timer."` |
| `timer_query` | `"{label} has {X minutes Y seconds} left."` per timer (speakable); none → `"No timers running."` |
| `yes` | only when `recipe.pending_timer_offer`: start that many minutes with `recipe.timer_label()`, then clear the offer |
| `no` | only when an offer is pending: `"Okay."`, then clear the offer |
| `ack` | only when `timers.acknowledge()` returns something: `"Got it."` |

  - Any other case, including `yes`/`no`/`ack` that don't apply, passes the original frame through.
  - When an intent is handled, it pushes `TTSSpeakFrame(reply)` (when there is a reply), then `LLMMessagesAppendFrame(messages=[{"role": "user", "content": text}, {"role": "assistant", "content": reply}], run_llm=False)`. It sets `path.value = "fast"`, calls `sink.recipe_state(recipe.snapshot())` after navigation, and does not push the transcription onward.
- Produces (`StateNoteInjector(FrameProcessor)`): `__init__(self, recipe: RecipeSession)`. It rewrites each final `TranscriptionFrame`'s text to `f"{text}\n\n[kitchen state: {note}]"`:
  - `note = f"recipe '{title}', step {i+1} of {n}, scaled for {servings} servings"`
  - with no recipe, `"no recipe loaded"`

- [ ] **Step 1: Write the failing pipeline tests** with `pipecat.tests.utils.run_test`, a `FakeSink` that records calls, and a `RecipeSession` loaded with a 3-step fixture recipe:

```python
async def test_engaged_next_is_fast_path():
    gate, router = make_gate_router(); sink = gate_sink
    down, _ = await run_test(Pipeline([gate, router]), frames_to_send=[tf("Chef, next")],
                             expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame])
    assert down[0].text.startswith("Step two") and path.value == "fast" and sink.heard == ["next"]
async def test_overheard_dropped():
    down, _ = await run_test(Pipeline([gate, router]), frames_to_send=[tf("did you call your mom back")], expected_down_frames=[])
    assert sink.overheard == ["did you call your mom back"]
async def test_unmatched_engaged_reaches_llm():
    down, _ = await run_test(Pipeline([gate, router]), frames_to_send=[tf("chef how much garlic")], expected_down_frames=[TranscriptionFrame])
    assert down[0].text == "how much garlic"
async def test_bare_wake_says_yes(): ...  # tf("hey chef") → [TTSSpeakFrame("Yes?")]
async def test_followup_after_bot_stops(): ...  # BotStoppedSpeakingFrame then tf("how much garlic") within window → TranscriptionFrame passes
async def test_router_cancel_ambiguous_asks():  # Review Focus 4
    timers.start(5, "pasta"); timers.start(3, "sauce")
    down, _ = await run_test(router, frames_to_send=[tf("cancel the timer")], expected_down_frames=[TTSSpeakFrame, LLMMessagesAppendFrame])
    assert down[0].text == "Which timer — pasta or sauce?" and len(timers.list()) == 2
async def test_yes_accepts_timer_offer(): ...  # recipe on step with timer_minutes=8 → tf("yes") → one timer of 8 min
async def test_state_note_injected(): ...  # StateNoteInjector rewrites text to include "step 1 of 3"
def test_latency_clock_once_per_turn(): c = LatencyClock(); c.user_stopped(1.0); assert c.bot_started(1.4) == 400 and c.bot_started(2.0) is None
```

  `tf(text)` builds `TranscriptionFrame(text=text, user_id="u", timestamp="now", finalized=True)`.
- [ ] **Step 2: Run** `uv run pytest tests/pipeline tests/unit/test_latency_clock.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `events.py`, the `AttentionGate`, `FastPathRouter` and `StateNoteInjector`. Expected: all pass.
- [ ] **Step 4: Commit**: `feat(kitchen): attention gate, fast-path router, events, latency`.

### Task 11: LLM tools, system prompt and tool-call evals

**Files:**
- Create: `src/kitchen_companion/tools.py`, `src/kitchen_companion/prompts.py`
- Test: `tests/unit/test_tools.py`, `tests/evals/conftest.py`, `tests/evals/test_tool_calls.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 5, 6 and 10 (`EventSink`).
- Produces (`prompts.py`): `SYSTEM_PROMPT: str`. It must contain:
  - "friendly, calm sous-chef"
  - "one or two short sentences"
  - "never guess quantities, temperatures, or times — use the tools"
  - "no lists or markdown"
  - "substitutions: answer from your own knowledge"
  - "the user's message may end with a [kitchen state: …] note; use it, never read it aloud"
- Produces (`tools.py`):
  - `class ToolHandlers`:
    - `__init__(self, recipe: RecipeSession, timers: TimerService, library: Library, sink: EventSink, on_recipe_loaded: Callable[[Recipe], Awaitable[None]])`
    - async methods that take `args: dict` and return a dict:
      - `search_recipes(query)` → `{"results": [{id, title}]}`
      - `load_recipe(recipe_id)` → `{"say": str}` or `{"error": ...}`
      - `get_ingredient(name)` → `{"say": str, "candidates": [...]}`
      - `scale_recipe(servings)`
      - `convert_units(quantity, from_unit, to_unit, ingredient=None)` → `{"say": str}` or `{"error": "…"}`
      - `go_to_step(step)`: an int, `"next"`, `"prev"` or `"repeat"`
      - `set_timer(minutes, label=None)`, `cancel_timer(label=None)`, `list_timers()`
  - `def tool_schemas(handlers: ToolHandlers) -> list[FunctionSchema]`. There is one `FunctionSchema(name, description, properties, required, handler=adapter)` per method. The adapter is `async def a(params: FunctionCallParams): await params.result_callback(await method(params.arguments))`.
  - `def to_anthropic_tools(schemas: list[FunctionSchema]) -> list[dict]`: `{name, description, input_schema: {type: "object", properties, required}}`, used by the evals.
- **Handler rules:**
  - Any exception becomes `{"error": "<speakable message>"}` and never propagates.
  - After state changes, handlers call `sink.recipe_state` or `sink.timers`.
  - `convert_units` with an impossible conversion returns `{"error": "I can't convert cups of spinach to grams reliably — roughly a handful per cup."}`, worded with the actual ingredient and units.

- [ ] **Step 1: Write the failing unit tests:**
  - `test_get_ingredient_scaled`
  - `test_convert_units_impossible_is_error_not_exception`
  - `test_load_recipe_calls_hook_and_emits_state`
  - `test_set_timer_emits_timers`
  - `test_unknown_recipe_id_error`
  - `test_schema_names_match_spec`: the set equals the 9 names in spec §5.8
  - `test_prompt_contains_rules`
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_tools.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Expected: all pass.
- [ ] **Step 4: Write the evals** (`@pytest.mark.eval`, skipped without a key).
  - Each eval calls `anthropic.AsyncAnthropic().messages.create(model="claude-haiku-5-5", max_tokens=1024, system=SYSTEM_PROMPT, tools=to_anthropic_tools(...), thinking={"type": "disabled"}, output_config={"effort": "low"}, messages=[...])`.
  - The user message includes a state note for the loaded fixture recipe (4 servings, includes butter).
  - Cases (spec §8):
    - `"how much butter do I need"` → a `tool_use` named `get_ingredient` with "butter" in `name`
    - `"make it for eight people"` → `scale_recipe` with `servings == 8`
    - a two-turn case: after the butter answer, `"convert that to grams"` → `convert_units` with `to_unit` in `{"g", "grams"}` and an ingredient containing "butter"
    - `"what can I use instead of buttermilk"` → no `tool_use`, ≤ 2 sentences, no `*`, `#` or `- `
    - `"set a timer for the pasta, eleven minutes"` → `set_timer` with `minutes == 11` and "pasta" in the label
- [ ] **Step 5: Run** `uv run pytest -m eval -v`. Expected: skipped without a key; passing with one.
- [ ] **Step 6: Commit**: `feat(kitchen): LLM tools, system prompt, tool-call evals`.

### Task 12: Server, kitchen registry and bot pipeline

**Files:**
- Create: `src/kitchen_companion/registry.py`, `src/kitchen_companion/bot.py`, `src/kitchen_companion/server.py`
- Test: `tests/unit/test_registry.py`, `tests/unit/test_server.py`

**Interfaces:**
- Consumes: everything above.
- Produces (`registry.py`):
  - `class Kitchen`:
    - Attributes: `id`, `recipe: RecipeSession`, `timers: TimerService`, `last_seen: float`
    - `attach(announce: Callable[[list[Timer], bool], Awaitable[None]]) -> None`
    - `detach() -> None`
    - `async on_due(timers, is_reminder)`: forwards to the attached announcer, or queues the call when detached. `attach` flushes the queue in order.
  - `class KitchenRegistry`:
    - `__init__(self, ttl_s: float = 6 * 3600, clock=time.monotonic)`
    - `get_or_create(kitchen_id: str) -> Kitchen`: starts `timers.run()` as an asyncio task.
    - `prune() -> list[str]`: removes kitchens unused for longer than the TTL and cancels their timer tasks.
  - `KITCHEN_ID_RE = r"^[A-Za-z0-9_-]{8,64}$"`
- Produces (`bot.py`): `async def run_bot(connection: SmallWebRTCConnection, kitchen: Kitchen, library: Library, settings: Settings) -> None`.
  1. Build `SmallWebRTCTransport(webrtc_connection=connection, params=TransportParams(audio_in_enabled=True, audio_out_enabled=True))`.
  2. Build the services per Global Constraints.
  3. Create `TurnPath`, `LatencyClock` and `AnnouncementGate`.
  4. Pipeline: `[transport.input(), stt, gate, router, StateNoteInjector(recipe), aggregators.user(), llm, tts, transport.output(), aggregators.assistant()]`.
  5. `PipelineTask(pipeline, observers=[LatencyObserver(...)])`.
  6. `RTVIEventSink(push=task.queue_frame)`.
  7. Track user and bot speaking: an observer feeds `AnnouncementGate` from `UserStartedSpeakingFrame` / `UserStoppedSpeakingFrame` and `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame`.
  8. `kitchen.attach(announce)`. `announce`:
     1. `await gate.wait_clear()`
     2. `task.queue_frame(TTSSpeakFrame(announcement_text(labels, recipe.next_step_text(), is_reminder)))`
     3. `attention.open_window()`
     4. `sink.timers(...)`
  9. `on_recipe_loaded(recipe)` pushes `STTUpdateSettingsFrame` with keyterms = ingredient names + `[wake_phrase]`, at most 50.
  10. `@task.rtvi.event_handler("on_client_ready")` sends `recipe_state` and `timers`.
  11. `@task.rtvi.event_handler("on_client_message")` handles:
      - `load_recipe`: `recipe.load`, then speak the intro
      - `goto_step`: `recipe.goto`, then speak
      - `engage`: `attention.arm_button()`
      - `ack_timer`: `timers.acknowledge()`
  12. On an `ErrorFrame` from the LLM, or when it hasn't produced a first token 8 s after a user turn reached it (detected by an observer timing `LLMContextFrame` → `LLMFullResponseStartFrame`), queue `TTSSpeakFrame("Sorry, I lost my train of thought — try that again?")` and call `sink.error(...)`. Fast-path commands are unaffected.
  13. On transport disconnect: `kitchen.detach()` and cancel the task.
  14. Run with `PipelineRunner(handle_sigint=False).run(task)`.
- Produces (`server.py`):
  - `def create_app(settings: Settings, registry: KitchenRegistry | None = None, library: Library | None = None, bot_runner=run_bot, importer=import_recipe) -> FastAPI`
  - `def run()`: `require(settings, REQUIRED)` followed by `uvicorn.run(create_app(...), host=settings.host, port=settings.port)`.
- **Endpoints:**
  - `POST /api/offer`: the body is `{sdp, type, pc_id?, restart_pc?, request_data: {kitchen_id}}`; a bad `kitchen_id` returns 422. It calls `SmallWebRTCRequestHandler.handle_web_request(SmallWebRTCRequest(...), callback)`, whose callback schedules `bot_runner(conn, registry.get_or_create(kid), library, settings)` as a background task. It returns the answer.
  - `PATCH /api/offer`: `handle_patch_request`.
  - `GET /api/recipes`: `[{id, title, servings, total_time_min}]`.
  - `GET /api/recipes/{id}`: 404 if missing.
  - `POST /api/recipes/import {url}`: `RecipeNotFound` or `ImportBlocked` → 422 `{"detail": human message}`; success → `library.add` and the recipe.
  - `GET /api/health`.
  - In production, serve `web/dist` at `/` when it exists.

- [ ] **Step 1: Write the failing tests:**
  - `test_registry_reuses_kitchen`
  - `test_registry_prunes_after_ttl` (fake clock)
  - `test_due_while_detached_is_queued_then_flushed`
  - `test_offer_rejects_bad_kitchen_id`
  - `test_recipes_list_and_get`
  - `test_import_maps_errors_to_422` (fake importer raises `ImportBlocked`)
  - `test_import_success_adds_to_library`
  - `test_health`
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_registry.py tests/unit/test_server.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `registry.py`, `server.py` and `bot.py`.
- [ ] **Step 4: Run the full suite** with `uv run pytest -v`. Expected: all pass.
- [ ] **Step 5: Smoke test:** run `uv run python -c "import kitchen_companion.bot, kitchen_companion.server"` (expected: no error). Then start `uv run kitchen-server` with dummy keys in the env and run `curl localhost:7860/api/health`. Expected: `{"ok": true}`.
- [ ] **Step 6: Commit**: `feat(kitchen): server, kitchen registry, Pipecat bot pipeline`.

### Task 13: Tablet PWA (Vite + React)

**Files:**
- Create in `kitchen-companion/web/`:
  - `package.json`, `vite.config.ts` (proxy `/api` → `http://localhost:7860`), `tsconfig.json`, `index.html`
  - `public/manifest.webmanifest`, `public/icon.svg`
  - `src/main.tsx`, `src/App.tsx`
  - `src/lib/types.ts`, `src/lib/api.ts`, `src/lib/kitchenId.ts`
  - `src/hooks/useWakeLock.ts`, `src/hooks/useKitchenState.ts`
  - `src/components/RecipePicker.tsx`, `CookMode.tsx`, `StepView.tsx`, `IngredientList.tsx`, `TimerRow.tsx`, `EngageButton.tsx`, `StatusOrb.tsx`, `TranscriptDrawer.tsx`
  - `src/styles.css`

**Interfaces:**
- Consumes:
  - REST from Task 12
  - RTVI server messages `{type: "recipe_state" | "timers" | "heard" | "overheard" | "latency" | "error", ...}` (Task 10)
  - Client messages `load_recipe`, `goto_step`, `engage` and `ack_timer` (Task 12)
- Produces:
  - `useKitchenState()`: a reducer over the server messages. The transcript keeps the last 30 lines, each `{kind: "heard" | "overheard" | "reply", text, latency?: {path, ms}}`.
  - `kitchenId()`: reads or creates `localStorage["kitchen_id"]`, made of 16 URL-safe characters.
  - `useWakeLock(active)`: acquires `navigator.wakeLock.request("screen")` and re-acquires it on `visibilitychange`. It fails silently where unsupported.

**Behavior:** per spec §5.12.
- Connect with `PipecatClient` and `SmallWebRTCTransport`, sending `kitchen_id` as the request data on the `/api/offer` call. Confirm the exact connect option names against the installed `@pipecat-ai/small-webrtc-transport` README.
- Auto-reconnect with backoff (1 s, 2 s, then 5 s repeatedly) while the page is visible.
- Picking a recipe card sends `load_recipe`.
- The import field POSTs `/api/recipes/import` and shows the 422 `detail` inline.
- **Cook mode:**
  - Current step at `clamp(2rem, 5vw, 3.5rem)`
  - A progress strip of tappable dots (each sends `goto_step`)
  - An ingredient checklist (ticks are local only)
  - Timers counting down locally from `ends_at_epoch`, amber under 60 s, pulsing when due (tap to ack)
  - A large "Hey Chef" button (sends `engage`)
  - An orb from the bot/user speaking callbacks
  - The transcript drawer shows overheard lines at 45% opacity and chips like "fast · 280 ms" or "llm · 1.1 s"
- Dark, high-contrast theme by default, landscape and portrait layouts, and no horizontal scroll at 375 px wide.

- [ ] **Step 1: Scaffold.** `package.json` has scripts `dev`, `build` and `typecheck` (`tsc --noEmit`), with deps pinned per Tech Stack. Run `npm install`.
- [ ] **Step 2: Implement** `lib/` and hooks, then the components.
- [ ] **Step 3: Run** `npm run typecheck && npm run build`. Expected: both succeed.
- [ ] **Step 4: Commit**: `feat(kitchen): tablet PWA cook mode`.

### Task 14: Docker, README and CI

**Files:**
- Create: `kitchen-companion/Dockerfile` (multi-stage: build `web/dist`, then a Python runtime serving the API and static files on 7860), `kitchen-companion/docker-compose.yml`, `kitchen-companion/README.md`
- Create: `.github/workflows/kitchen-companion.yml`

**Interfaces:**
- Compose: one `kitchen` service on port `7860:7860` with `env_file: .env`. There is no media server. A WebRTC UDP note goes in the README.
- **CI** (`paths: ["kitchen-companion/**", ".github/workflows/kitchen-companion.yml"]`):
  - Job `test`: setup-uv, `uv sync`, `uv run ruff check`, `uv run pytest`; then `npm ci && npm run typecheck && npm run build` in `web/`.
  - Job `evals`: runs `uv run pytest -m eval` only when the `ANTHROPIC_API_KEY` secret is present.
- **README sections:**
  1. What it is
  2. Why it's built this way (spec §2)
  3. The pipeline diagram
  4. The attention gate and fast path, explained with the latency chips
  5. Quick start with Docker
  6. Dev setup
  7. Using it on a real tablet (HTTPS or tunnel; the microphone needs a secure context)
  8. Keys
  9. Tests and evals
  10. Known limitations: wake word detected from the transcript, single device per kitchen

- [ ] **Step 1: Write the files.**
- [ ] **Step 2: Run** `docker compose -f kitchen-companion/docker-compose.yml config -q` (expected: exit 0), then `uv run ruff check && uv run pytest` (expected: clean and passing).
- [ ] **Step 3: Commit**: `chore(kitchen): docker, README, CI workflow`.
