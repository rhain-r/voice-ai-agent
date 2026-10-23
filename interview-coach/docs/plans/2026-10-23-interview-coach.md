# Interview Coach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LiveKit voice agent that runs a mock interview for any role and produces a scorecard: per-answer grades with evidence, speech metrics, and a coaching plan.

**Architecture:** Four Python processes share one package, `interview_coach`:
- **Agent worker** (LiveKit Agents): real-time only.
- **MCP server:** the question bank.
- **FastAPI:** sessions, tokens, reports in SQLite, and the LangGraph scorecard, run as a background task.

A Next.js app is the UI. All the pure logic (analytics, question selection, aggregation, latency, text cleanup) lives in modules with no I/O and is unit-tested without keys.

**Tech Stack:**
- Python 3.12 (uv)
- livekit-agents 1.8.8 with the anthropic, deepgram, silero, turn-detector, cartesia and mcp extras
- livekit-api, mcp 2.3.0, langgraph 1.2.16, anthropic ≥ 1.17
- FastAPI, pydantic-settings, httpx
- pytest + pytest-asyncio, ruff
- Next.js 16.4, @livekit/components-react 2.9.24, livekit-client 2.23.0

**Spec:** `interview-coach/docs/specs/2026-10-23-interview-coach-design.md`

## Global Constraints

**Models.** Use these exact strings, with no date suffixes:
- live: `claude-sonnet-5-5`
- fallback: `claude-haiku-5-5`
- grader: `claude-opus-5-5`

**Claude API rules:**
- Never send `temperature`, `top_p` or `top_k`. They return a 400 on these models.
- Never send a forced `tool_choice` (`any` or `tool`). Leave it at the plugin default, `auto`.
- Live-turn thinking:
  - Sonnet 5.5: `thinking={"type": "between_tools"}` and `output_config={"effort": "low"}`
  - Haiku 5.5: `thinking={"type": "disabled"}` and `output_config={"effort": "low"}`
- The grader omits `thinking` (Opus 5.5 always runs adaptive) and uses `output_config={"effort": "high"}`. It sets `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"`, and checks `stop_reason == "refusal"` before reading `parsed_output`.

**LiveKit 1.8:**
- Configure turn-taking only through `turn_handling={...}`. The flat parameters (`min_endpointing_delay` etc.) are deprecated.
- The agent name is exactly `interview-coach`, with explicit dispatch only.

**Turn values** (from the spec):

| Setting | Value |
|---|---|
| endpointing `min_delay` | 0.8 |
| endpointing `max_delay` | 6.0 |
| interruption `mode` | `"adaptive"` |
| interruption `min_words` | 2 |
| `resume_false_interruption` | True |
| `false_interruption_timeout` | 1.5 |
| preemptive generation | enabled |
| `user_away_timeout` | 25.0 |

**Other values:**
- STT: Deepgram `nova-3`, `filler_words=True`, `smart_format=True`.
- TTS default: Deepgram `aura-2-andromeda-en`; Cartesia is the fallback only when `CARTESIA_API_KEY` is set.
- Ports: LiveKit 7880, API 8000, MCP 8765 (path `/mcp`), web 3000.
- Text-stream topics: `coach.metrics` and `coach.progress`.
- Agent → API auth header: `X-Agent-Secret`.
- SQLite file: `data/coach.db`. Failed completions spill to `data/failed_completions/{session_id}.json`.
- Unit tests must pass with no API keys. Eval tests are marked `@pytest.mark.eval` and skipped unless `ANTHROPIC_API_KEY` is set.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Known risk:** the LiveKit Anthropic plugin drops `thinking` blocks from chat history. If evals show 400s on Sonnet tool turns, set `LIVE_MODEL=claude-haiku-5-5`. The FallbackAdapter already covers this at runtime.

## Review Focus

1. **A candidate leaves mid-interview, or `end_interview` and a disconnect both fire.** Exactly one completion is posted, marked `partial` when questions remain. Test: `test_completion_fires_once` (Task 9).
2. **A candidate stays silent for a long time.** The agent checks in once per question, not every 25 s. Test: `test_away_checkin_once_per_question` (Task 9).
3. **A candidate skips a question ("pass", or no speech).** Analytics returns zeros, not a ZeroDivisionError. The scorecard lists the answer as skipped and doesn't grade it. Tests: `test_answer_with_no_segments` (Task 3) and `test_skipped_answers_not_graded` (Task 6).
4. **A role string is odd: very long, emoji, mixed case.** The API returns 422 for roles over 80 chars. `role_family` matches case-insensitively. Tests: `test_create_session_rejects_long_role` (Task 7) and `test_role_family_case_insensitive` (Task 4).
5. **The grader refuses or the API errors.** The report becomes `failed` with a readable error, while speech metrics and transcript are still returned. Test: `test_failed_scorecard_keeps_speech` (Task 7).

---

### Task 1: Project scaffold and config

**Files:**
- Create: `interview-coach/pyproject.toml`, `interview-coach/.env.example`
- Create: `interview-coach/src/interview_coach/__init__.py`, `interview-coach/src/interview_coach/config.py`
- Create: `interview-coach/tests/conftest.py`
- Test: `interview-coach/tests/unit/test_config.py`

**Interfaces:**
- Produces:
  - `class Settings(BaseSettings)`. Its fields are exactly the variables in spec §9, lower-snake-cased, with the spec's defaults. It reads `.env`.
  - `def missing_keys(settings: Settings, required: Sequence[str]) -> list[str]`
  - `def require(settings: Settings, required: Sequence[str]) -> None`. It raises `SystemExit("Missing required environment variables: A, B")`.
  - Constants:
    - `AGENT_REQUIRED = ("anthropic_api_key", "deepgram_api_key", "livekit_url", "livekit_api_key", "livekit_api_secret", "agent_shared_secret")`
    - `API_REQUIRED = ("anthropic_api_key", "livekit_url", "livekit_api_key", "livekit_api_secret", "agent_shared_secret")`

- [ ] **Step 1: Write `pyproject.toml`.**
  - Project `interview-coach`, `requires-python = ">=3.12,<3.13"`.
  - Dependencies pinned per Tech Stack, plus `uvicorn`.
  - Dev group: `pytest`, `pytest-asyncio`, `ruff`.
  - Scripts:
    - `coach-agent = "interview_coach.agent.worker:main"`
    - `coach-api = "interview_coach.api.main:run"`
    - `coach-mcp = "interview_coach.mcp_server.server:main"`
  - `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `markers = ["eval: needs ANTHROPIC_API_KEY"]`, `addopts = "-m 'not eval'"`.
  - Write `.env.example` verbatim from spec §9.

- [ ] **Step 2: Write the failing tests.**

```python
def test_missing_keys_reports_empty_and_unset():
    s = Settings(_env_file=None, anthropic_api_key="", deepgram_api_key="x")
    assert missing_keys(s, ("anthropic_api_key", "deepgram_api_key")) == ["anthropic_api_key"]

def test_require_exits_with_upper_names():
    s = Settings(_env_file=None, anthropic_api_key="")
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        require(s, ("anthropic_api_key",))

def test_defaults_match_spec():
    s = Settings(_env_file=None)
    assert (s.live_model, s.fallback_model, s.grader_model) == ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5")
    assert s.mcp_url == "http://localhost:8765/mcp" and s.tts_provider == "deepgram"
```

- [ ] **Step 3: Run** `cd interview-coach && uv sync && uv run pytest tests/unit/test_config.py -v`. Expected: FAIL with an ImportError.
- [ ] **Step 4: Implement `config.py`.**
- [ ] **Step 5: Run** the same command. Expected: 3 passed.
- [ ] **Step 6: Commit**: `git add interview-coach && git commit -m "feat(coach): scaffold project and config"`.

### Task 2: Speakable text normalizer

**Files:**
- Create: `src/interview_coach/agent/__init__.py`, `src/interview_coach/agent/speakable.py`
- Test: `tests/unit/test_speakable.py`

**Interfaces:**
- Produces:
  - `def normalize(text: str) -> str`
  - `async def normalize_stream(chunks: AsyncIterable[str]) -> AsyncIterator[str]`. It buffers until the last whitespace, yields `normalize(buffered_prefix)`, and flushes the remainder at the end.

- [ ] **Step 1: Write a parametrized `test_normalize`.**

| Input | Expected output |
|---|---|
| `"**Great** answer"` | `"Great answer"` |
| `"# Next"` | `"Next"` |
| `"- first point"` | `"first point"` |
| `` "`code`" `` | `"code"` |
| `"40% faster"` | `"40 percent faster"` |
| `"R&D"` | `"R and D"` |
| `"e.g. a cache"` | `"for example a cache"` |
| `"see https://x.io/a"` | `"see the link on screen"` |
| `"plain"` | `"plain"` |

  Add `test_normalize_stream_joins_split_tokens`: chunks `["**Gre", "at** ans", "wer"]` → `"".join(out) == "Great answer"`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_speakable.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Use regexes compiled once at module level.
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(coach): speakable text normalizer`.

### Task 3: Speech analytics

**Files:**
- Create: `src/interview_coach/agent/analytics.py`
- Test: `tests/unit/test_analytics.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Word: text: str; start: float; end: float`
  - `@dataclass(frozen=True) class Segment: text: str; start: float; end: float; words: tuple[Word, ...] = ()`
  - `@dataclass class AnswerMetrics`:
    - `index: int`, `duration_s: float`, `word_count: int`, `wpm: float`
    - `filler_count: int`, `fillers_per_min: float`, `verbal_tics: dict[str, int]`
    - `longest_pause_s: float`, `pauses_over_3s: int`, `thinking_time_s: float | None`
    - `pace_band: Literal["slow", "conversational", "fast", "n/a"]`
  - `@dataclass class SessionMetrics: answers: list[AnswerMetrics]; avg_wpm: float; fillers_per_min: float; talk_ratio: float; avg_thinking_time_s: float | None`
  - `def count_fillers(text: str) -> int`. Fillers are um, uh, er, erm, hmm, umm and uhm, matched case-insensitively on word boundaries.
  - `def count_tics(text: str) -> dict[str, int]`. Tics are `like`, `you know`, `basically`, `literally`, `kind of` and `sort of`. Only non-zero keys are returned.
  - `def pace_band(wpm: float) -> str`:
    - below 110 → `slow`
    - 110–170 → `conversational`
    - above 170 → `fast`
    - 0 → `n/a`
  - `class SpeechAnalytics`:
    - `start_question(index: int, at: float) -> None`
    - `add_segment(seg: Segment) -> None`: ignored before the first question.
    - `add_agent_speech(start: float, end: float) -> None`
    - `segments_for(index: int) -> list[Segment]`
    - `answer_metrics(index: int) -> AnswerMetrics`
    - `session_metrics() -> SessionMetrics`

**Rules** (these pin choices the tests rely on):
- Answer duration runs from the first word start to the last word end. Words come from `Segment.words`, falling back to the segment bounds when there are no words.
- `wpm = word_count / (duration_s / 60)`. Word count is whitespace tokens of the joined text, fillers included.
- A gap between consecutive words (word-level) or segments (segment-level) counts as a pause **only if no agent speech interval overlaps it**.
- `thinking_time_s` = the first word start of the answer minus the end of the latest agent speech interval that ends after `start_question` and before that word. `None` if there is no such interval.
- `talk_ratio` = candidate speech seconds ÷ (candidate + agent speech seconds). Candidate speech seconds is the sum of segment durations.

- [ ] **Step 1: Write the failing tests.**

```python
def test_basic_answer_metrics():
    a = SpeechAnalytics(); a.start_question(0, at=0.0); a.add_agent_speech(0.0, 4.0)
    a.add_segment(Segment("um so I led the migration", 7.0, 10.0))
    m = a.answer_metrics(0)
    assert (m.word_count, m.filler_count, round(m.wpm), m.thinking_time_s) == (6, 1, 120, 3.0)

def test_pause_ignored_when_agent_spoke_in_gap():
    a = SpeechAnalytics(); a.start_question(0, at=0.0)
    a.add_segment(Segment("first part", 1.0, 2.0)); a.add_agent_speech(2.5, 6.0)
    a.add_segment(Segment("second part", 7.0, 8.0))
    assert a.answer_metrics(0).longest_pause_s == 0.0

def test_long_pause_counted():
    a = SpeechAnalytics(); a.start_question(0, at=0.0)
    a.add_segment(Segment("first", 1.0, 2.0)); a.add_segment(Segment("second", 5.5, 6.0))
    m = a.answer_metrics(0); assert (m.longest_pause_s, m.pauses_over_3s) == (3.5, 1)

def test_word_level_pauses_used_when_present(): ...  # words [("I",1,1.2),("think",4.6,5.0)] → longest_pause_s == 3.4

def test_tics_and_pace_band():
    assert count_tics("it was like, you know, basically fine") == {"like": 1, "you know": 1, "basically": 1}
    assert [pace_band(x) for x in (0, 100, 140, 200)] == ["n/a", "slow", "conversational", "fast"]

def test_answer_with_no_segments():  # Review Focus 3
    a = SpeechAnalytics(); a.start_question(0, at=0.0)
    m = a.answer_metrics(0); assert (m.word_count, m.wpm, m.pace_band, m.thinking_time_s) == (0, 0.0, "n/a", None)

def test_segments_attributed_to_current_question_and_talk_ratio():
    a = SpeechAnalytics(); a.add_segment(Segment("ignored", 0, 1))
    a.start_question(0, 1.0); a.add_agent_speech(1.0, 3.0); a.add_segment(Segment("one two", 4.0, 6.0))
    a.start_question(1, 7.0); a.add_segment(Segment("three", 8.0, 9.0))
    assert [s.text for s in a.segments_for(0)] == ["one two"]
    assert round(a.session_metrics().talk_ratio, 2) == 0.6  # 3s candidate / 5s total
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_analytics.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `analytics.py`** following the rules above.
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(coach): speech analytics`.

### Task 4: Question bank and MCP server

**Files:**
- Create: `src/interview_coach/mcp_server/__init__.py`, `bank.py`, `server.py`, `question_bank.json`
- Test: `tests/unit/test_bank.py`, `tests/unit/test_mcp_server.py`

**Interfaces:**
- Produces (`bank.py`, pure):
  - `class QuestionItem(BaseModel): id: str; text: str; competency: str; style: Literal["behavioral", "technical"]; levels: list[str]; good_answer_covers: list[str]`
  - `LEVELS = ("intern", "junior", "mid", "senior", "staff")`
  - `def role_family(role: str) -> Literal["software", "data", "ai_ml", "product", "design", "general"]`
  - `def question_plan(role: str, level: str, style: Literal["behavioral", "technical", "mixed"], count: int, seed: str) -> list[QuestionItem]`
  - `def rubric(style: str) -> dict[str, dict[str, str]]`: dimension → `{"1": ..., "3": ..., "5": ...}` for `structure`, `specificity`, `impact`, `relevance` and `communication`.
- Produces (`server.py`):
  - `mcp = MCPServer("interview-coach-questions")` with tools `list_role_families()`, `get_question_plan(role, level, style, count, seed="")` (returns `{"family": str, "items": [QuestionItem dict]}`) and `get_rubric(style)`.
  - `def main()` runs `mcp.run("streamable-http", host="0.0.0.0", port=8765)`.
  - Use `from mcp.server.mcpserver import MCPServer` and `@mcp.tool()`.

**Bank content** (`question_bank.json`):
- At least 10 general behavioral items, covering conflict, failure, leadership, ambiguity, prioritization, feedback, influence, deadline, learning and ownership.
- For each of the 5 families, at least 4 technical-conceptual items, phrased so they can be answered without a whiteboard (e.g. "Walk me through how you'd design…").
- At least 2 family-specific behavioral items each.
- Every item tags at least 2 levels.

**`role_family` keyword map:** case-insensitive substring match; order matters, first match wins.

| Keywords | Family |
|---|---|
| `machine learning`, `ml`, `ai` (as whole words) | `ai_ml` |
| `data`, `analyst`, `analytics` | `data` |
| `product manager`, `product owner`, `pm` | `product` |
| `designer`, `ux`, `ui` | `design` |
| `engineer`, `developer`, `swe`, `programmer` | `software` |
| anything else | `general` |

**`question_plan` rules:**
- Clamp `count` to 1..10.
- Seed with `random.Random(f"{seed}:{role}:{level}:{style}")`.
- Candidate pools:
  - behavioral = general behavioral + family behavioral
  - technical = family technical, or general technical when the family is `general`
- Prefer items tagged with `level`. If the pool is short, top up from other levels.
- `mixed` alternates, starting behavioral.
- Never repeat an id.

- [ ] **Step 1: Write the failing tests.**

```python
@pytest.mark.parametrize("role,fam", [("Senior Software Engineer","software"),("ML Engineer","ai_ml"),
    ("Data Analyst","data"),("Product Manager","product"),("UX Designer","design"),("Chef","general")])
def test_role_family(role, fam): assert role_family(role) == fam

def test_role_family_case_insensitive(): assert role_family("mACHINE lEARNING researcher") == "ai_ml"  # Review Focus 4

def test_plan_count_unique_deterministic():
    p1 = question_plan("Data Analyst", "junior", "mixed", 5, seed="s1")
    assert len(p1) == 5 and len({q.id for q in p1}) == 5
    assert [q.id for q in p1] == [q.id for q in question_plan("Data Analyst", "junior", "mixed", 5, seed="s1")]
    assert [q.style for q in p1] == ["behavioral", "technical", "behavioral", "technical", "behavioral"]

def test_plan_prefers_level(): assert all("senior" in q.levels for q in question_plan("Software Engineer","senior","behavioral",3,"x"))
def test_count_clamped(): assert len(question_plan("x","mid","behavioral",50,"s")) == 10
def test_rubric_shape(): assert set(rubric("behavioral")) == {"structure","specificity","impact","relevance","communication"}
```

  Add `test_mcp_tool_returns_plan` in `test_mcp_server.py`. Use `async with mcp.Client(server.mcp) as c`, call `get_question_plan` with `{"role":"Data Analyst","level":"junior","style":"mixed","count":3,"seed":"s1"}`, then `json.loads(result.content[0].text)`. Assert `family == "data"` and that the item ids equal `question_plan(...)` called directly.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_bank.py tests/unit/test_mcp_server.py -v`. Expected: FAIL.
- [ ] **Step 3: Write `question_bank.json`, then implement `bank.py` and `server.py`.**
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Smoke test:** `uv run coach-mcp`. Expected: uvicorn logs `127.0.0.1:8765` or `0.0.0.0:8765`. Stop it.
- [ ] **Step 6: Commit**: `feat(coach): question bank and MCP server`.

### Task 5: Question plan client with bundled fallback

**Files:**
- Create: `src/interview_coach/agent/question_source.py`
- Test: `tests/unit/test_question_source.py`

**Interfaces:**
- Consumes: `bank.question_plan`, `bank.QuestionItem`, `server.mcp` (Task 4).
- Produces: `async def fetch_plan(target: str | Any, *, role: str, level: str, style: str, count: int, seed: str, timeout: float = 3.0) -> tuple[list[QuestionItem], Literal["mcp", "bundled"]]`.
  - `target` is the MCP URL, or an `MCPServer` instance in tests. It is passed to `mcp.Client`.
  - Any exception or timeout logs a warning and returns `(bank.question_plan(...), "bundled")`.

- [ ] **Step 1: Write the failing tests.**
  - `test_fetch_from_mcp` (target `server.mcp`): source is `"mcp"` and there are 3 items.
  - `test_falls_back_when_unreachable` (target `"http://127.0.0.1:9/mcp"`, `timeout=0.5`): source is `"bundled"` and there are 3 items.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** with `asyncio.wait_for` around the `Client` block.
- [ ] **Step 4: Run.** Expected: 2 passed.
- [ ] **Step 5: Commit**: `feat(coach): MCP question plan client with fallback`.

### Task 6: Scorecard models and LangGraph pipeline

**Files:**
- Create: `src/interview_coach/scorecard/__init__.py`, `models.py`, `graph.py`
- Test: `tests/unit/test_scorecard.py`

**Interfaces:**
- Produces (`models.py`):
  - `class SessionInfo(BaseModel): role: str; level: str; style: str`
  - `class QAItem(BaseModel): index: int; question: str; competency: str; transcript: str; metrics: dict = {}`
  - `class DimensionScores(BaseModel)`: `structure`, `specificity`, `impact`, `relevance` and `communication`, each `int` with `Field(ge=1, le=5)`.
  - `class AnswerGrade(BaseModel): scores: DimensionScores; strengths: list[str] = Field(max_length=2); improvements: list[str] = Field(max_length=2); evidence_quotes: list[str]; one_line_verdict: str`
  - `class CoachingPlan(BaseModel): top_fixes: list[str] = Field(min_length=3, max_length=3); rewritten_answer: str; practice_drill: str`
  - `class GradedAnswer(BaseModel): index: int; grade: AnswerGrade`
  - `class Scorecard(BaseModel)`:
    - `overall: int`, `dimension_averages: dict[str, float]`, `weakest_dimension: str`
    - `best_index: int`, `weakest_index: int`, `skipped: list[int]`
    - `graded: list[GradedAnswer]`, `coaching: CoachingPlan`
- Produces (`graph.py`):
  - `class Grader(Protocol)`:
    - `async def grade(self, item: QAItem, rubric: dict, session: SessionInfo) -> AnswerGrade`
    - `async def coach(self, items: list[QAItem], graded: list[GradedAnswer], session: SessionInfo) -> CoachingPlan`
  - `class GradingRefused(RuntimeError)`
  - `class ClaudeGrader`: `__init__(self, client: anthropic.AsyncAnthropic, model: str = "claude-opus-5-5")`. Both methods call `client.beta.messages.parse(model=..., max_tokens=16000, betas=["server-side-fallback-2026-07-01"], fallbacks="default", output_config={"effort": "high"}, output_format=<Model>, system=..., messages=[...])`. They raise `GradingRefused` when `stop_reason == "refusal"`.
  - `WEIGHTS = {"structure": 1.5, "impact": 1.5, "specificity": 1.0, "relevance": 1.0, "communication": 1.0}`
  - `def aggregate(graded: list[GradedAnswer]) -> dict`: returns `overall`, `dimension_averages`, `weakest_dimension`, `best_index` and `weakest_index`.
  - `def build_graph(grader: Grader)` returns a compiled `StateGraph`.
  - `async def run_scorecard(grader: Grader, session: SessionInfo, items: list[QAItem], rubric: dict) -> Scorecard`

**Graph:** `START → fan_out (conditional edges returning Send("grade_answer", {...}) per item with a non-empty transcript) → grade_answer → aggregate → coach → END`.
- The state key `graded` uses the reducer `operator.add`.
- Items with an empty or whitespace-only transcript go to `skipped` and are not graded.
- If every item is skipped, raise `ValueError("no answers to grade")`.

**Aggregate math:**
- Per answer: weighted mean over dimensions using `WEIGHTS`.
- `overall = round((mean of per-answer weighted means − 1) / 4 × 100)`.
- `dimension_averages` are plain means rounded to 2 places.
- `weakest_dimension` is the lowest average; ties go to the first in `WEIGHTS` order.
- `best_index` and `weakest_index` come from the per-answer weighted means.

**Grader prompts:**
- `grade` includes the role, level, the question, the "good answer covers" hints when present, the rubric anchors, and the transcript. It instructs: "quote only words the candidate said".
- `coach` instructs: "rewrite the weakest answer in STAR form using only facts the candidate gave".

- [ ] **Step 1: Write the failing tests** with a `FakeGrader` that returns fixed scores per index and records calls.

```python
def test_aggregate_all_fives_is_100(): assert aggregate([ga(0, 5,5,5,5,5)])["overall"] == 100
def test_aggregate_all_ones_is_0(): assert aggregate([ga(0, 1,1,1,1,1)])["overall"] == 0
def test_aggregate_weighted():  # structure/impact weighted 1.5
    r = aggregate([ga(0, structure=5, specificity=3, impact=1, relevance=3, communication=3)])
    assert r["overall"] == 50 and r["weakest_dimension"] == "impact"
async def test_graph_grades_each_answer_once():
    g = FakeGrader(); sc = await run_scorecard(g, SESSION, [qa(0,"a"), qa(1,"b"), qa(2,"c")], RUBRIC)
    assert sorted(g.graded_indexes) == [0, 1, 2] and len(sc.graded) == 3 and g.coach_calls == 1
async def test_skipped_answers_not_graded():  # Review Focus 3
    sc = await run_scorecard(FakeGrader(), SESSION, [qa(0, "real answer"), qa(1, "  ")], RUBRIC)
    assert sc.skipped == [1] and [x.index for x in sc.graded] == [0]
async def test_all_skipped_raises():
    with pytest.raises(ValueError): await run_scorecard(FakeGrader(), SESSION, [qa(0, "")], RUBRIC)
async def test_claude_grader_refusal_raises():  # fake client whose beta.messages.parse returns stop_reason="refusal"
    with pytest.raises(GradingRefused): await ClaudeGrader(FakeClient(refuse=True)).grade(qa(0,"x"), RUBRIC, SESSION)
async def test_claude_grader_request_shape():
    c = FakeClient(); await ClaudeGrader(c).grade(qa(0,"x"), RUBRIC, SESSION)
    kw = c.last_kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and "temperature" not in kw and "thinking" not in kw
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_scorecard.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `models.py` and `graph.py`.**
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(coach): LangGraph scorecard pipeline`.

### Task 7: API (FastAPI, SQLite, token minting, background scorecard)

**Files:**
- Create: `src/interview_coach/api/__init__.py`, `db.py`, `main.py`
- Test: `tests/unit/test_api.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `run_scorecard`, `ClaudeGrader`, `QAItem`, `SessionInfo` and `Scorecard` (Task 6), `bank.rubric` (Task 4).
- Produces:
  - `class SessionSetup(BaseModel)`:
    - `role: str = Field(min_length=2, max_length=80)`
    - `level: Literal[*LEVELS]`
    - `style: Literal["behavioral", "technical", "mixed"]`
    - `count: int = Field(ge=1, le=10)`
  - `class CompletionPayload(BaseModel)`:
    - `status: Literal["completed", "partial"]`
    - `transcript: list[dict]`: each `{role, text, at}`
    - `qa_items: list[QAItem]`
    - `speech: dict`: `SessionMetrics` as a dict
    - `latency: dict`: `{p50_ms, p95_ms, turns}`
  - `class Store`:
    - `__init__(path: Path)`
    - `create(setup: SessionSetup) -> str`: returns a session id of the form `"s_" + 10 random lowercase alphanumerics`.
    - `complete(id, payload: CompletionPayload) -> None`
    - `set_report(id, status: Literal["pending", "ready", "failed"], scorecard: dict | None, error: str | None) -> None`
    - `get(id) -> dict | None`
    - `list(limit: int = 20) -> list[dict]`
  - `def mint_token(settings, session_id: str, setup: SessionSetup) -> str`. The room name is `f"coach-{session_id}"`, the identity is `f"candidate-{session_id}"`, and it carries `api.VideoGrants(room_join=True, room=room)` plus `.with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name="interview-coach", metadata=json.dumps({"session_id": ..., **setup.model_dump()}))]))`.
  - `def create_app(settings: Settings, store: Store | None = None, grader_factory: Callable[[], Grader] | None = None) -> FastAPI`
  - `def run()`: `require(settings, API_REQUIRED)` followed by `uvicorn.run(create_app(...), host="0.0.0.0", port=8000)`.

**Endpoints** follow spec §5.8 exactly.
- `POST /api/sessions` returns `{session_id, token, livekit_url}`.
- `POST /api/sessions/{id}/complete` returns 202. It returns 401 if `X-Agent-Secret` doesn't match, and 404 for an unknown id.
- `GET /api/sessions/{id}/report` returns `{status, session, speech, latency, transcript, scorecard, error}`.
  - The status is `pending` until the background task finishes, and `in_progress` before completion arrives.
- `POST /api/sessions/{id}/report/retry` re-runs the scorecard. It is only allowed from `failed`, otherwise 409.
- Background job: `run_scorecard(grader_factory(), SessionInfo(...), payload.qa_items, rubric(style))`.
  - On success: `ready` plus `scorecard.model_dump()`.
  - On any exception: `failed` plus `f"{type(e).__name__}: {e}"`.
- CORS allows `http://localhost:3000`.

- [ ] **Step 1: Write the failing tests** (`TestClient`, `tmp_path` store, FakeGrader from Task 6 tests moved to `tests/fakes.py`):

```python
def test_create_session_returns_dispatch_token(client):
    r = client.post("/api/sessions", json=SETUP); body = r.json()
    claims = jwt_claims(body["token"])  # base64-decode middle segment, no verification
    agent = claims["roomConfig"]["agents"][0]
    assert agent["agentName"] == "interview-coach" and json.loads(agent["metadata"])["role"] == SETUP["role"]
def test_create_session_rejects_long_role(client):  # Review Focus 4
    assert client.post("/api/sessions", json={**SETUP, "role": "x" * 81}).status_code == 422
def test_complete_requires_secret(client, sid): assert client.post(f"/api/sessions/{sid}/complete", json=PAYLOAD).status_code == 401
def test_complete_then_report_ready(client, sid):
    assert post_complete(client, sid).status_code == 202
    r = client.get(f"/api/sessions/{sid}/report").json(); assert r["status"] == "ready" and r["scorecard"]["overall"] >= 0
def test_failed_scorecard_keeps_speech(failing_client, sid):  # Review Focus 5
    post_complete(failing_client, sid); r = failing_client.get(f"/api/sessions/{sid}/report").json()
    assert r["status"] == "failed" and r["error"] and r["speech"] == PAYLOAD["speech"] and r["transcript"]
def test_retry_only_from_failed(client, sid): post_complete(client, sid); assert client.post(f"/api/sessions/{sid}/report/retry").status_code == 409
def test_unknown_session_404(client): assert client.get("/api/sessions/s_nope/report").status_code == 404
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_api.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `db.py`** (stdlib `sqlite3` with JSON text columns, and `check_same_thread=False` behind a lock) **and `main.py`.**
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(coach): sessions API with background scorecard`.

### Task 8: Voice LLM wrapper, prompts and Interviewer agent

**Files:**
- Create: `src/interview_coach/agent/llm.py`, `prompts.py`, `interviewer.py`
- Test: `tests/unit/test_llm_options.py`, `tests/unit/test_interviewer.py`

**Interfaces:**
- Consumes:
  - `SpeechAnalytics`, `Segment` and `Word` (Task 3)
  - `QuestionItem` (Task 4)
  - `speakable.normalize_stream` (Task 2)
- Produces (`llm.py`):
  - `def voice_request_options(model: str, effort: str = "low") -> dict`
    - Sonnet 5.5 → `{"thinking": {"type": "between_tools"}, "output_config": {"effort": effort}}`
    - Haiku 5.5 → `{"thinking": {"type": "disabled"}, "output_config": {"effort": effort}}`
    - otherwise → `{"output_config": {"effort": effort}}`
  - `class ClaudeVoiceLLM(livekit.plugins.anthropic.LLM)`: `__init__(self, *, model: str, effort: str = "low", **kw)`. It overrides `chat(...)` to call `super().chat(..., extra_kwargs={**voice_request_options(...), **(extra_kwargs or {})})`.
- Produces (`prompts.py`):
  - `VOICE_RULES: str`
  - `def interviewer_instructions(setup: InterviewSetup, total: int) -> str`
  - `class InterviewSetup(BaseModel): session_id: str; role: str; level: str; style: str; count: int`
- Produces (`interviewer.py`):
  - `class Interviewer(livekit.agents.Agent)`
  - `__init__(self, *, setup: InterviewSetup, plan: list[QuestionItem], analytics: SpeechAnalytics, on_progress: Callable[[dict], Awaitable[None]], on_finish: Callable[[str], Awaitable[None]], clock: Callable[[], float] = time.monotonic)`
  - Plain methods, which the tests call directly:
    - `async def advance_question(self) -> str`
    - `async def finish(self, reason: str) -> None`: idempotent; the second call is a no-op. `reason` is free text. The tool passes its literal, and the worker also passes `"disconnected"` and `"stt_failure"`.
    - `@property current_index -> int`: -1 before the first question.
  - Tools delegate to the plain methods:
    - `@function_tool async def next_question(self, context: RunContext) -> str`
    - `@function_tool async def end_interview(self, context: RunContext, reason: Literal["completed", "candidate_requested", "timeout"]) -> str`
  - `on_enter`: `self.session.generate_reply(instructions="Greet the candidate warmly, say there are N questions and they can take their time, then call next_question.")`
  - `stt_node`: wraps `Agent.default.stt_node`. For each `SpeechEvent` of type `FINAL_TRANSCRIPT`, it builds a `Segment` from `alternatives[0]` (`text`, `start_time`, `end_time`, and `words` mapped to `Word`) and calls `analytics.add_segment`. It yields events unchanged.
  - `tts_node`: `Agent.default.tts_node(self, speakable.normalize_stream(text), model_settings)`

**`advance_question` behavior:**
- Increments the index and calls `analytics.start_question(i, clock())`.
- Awaits `on_progress({"index": i, "total": n, "competency": q.competency})`.
- Returns `f"Question {i+1} of {n} ({q.competency}): {q.text}\nA strong answer covers: {', '.join(q.good_answer_covers)}. Ask it naturally, in your own words."`
- Past the end, returns `"NO_MORE_QUESTIONS: ask whether they have questions for you, answer briefly, then say goodbye and call end_interview with reason completed."`

**`interviewer_instructions` must contain:**
- the role, level and total
- `VOICE_RULES`: "one or two sentences", "one question at a time", "no lists, markdown, or emoji", "say numbers as words a person would say"
- "Never give feedback or scores during the interview; say they'll get a detailed scorecard at the end."
- "Ask at most two follow-ups per question, each probing what's missing — usually the result or their personal contribution."
- "Repeating or rephrasing a question on request is not a follow-up."
- "Call next_question to move on; call end_interview if the candidate asks to stop."

- [ ] **Step 1: Write the failing tests.**

```python
def test_voice_options_sonnet(): assert voice_request_options("claude-sonnet-5-5") == {"thinking": {"type": "between_tools"}, "output_config": {"effort": "low"}}
def test_voice_options_haiku(): assert voice_request_options("claude-haiku-5-5")["thinking"] == {"type": "disabled"}
def test_voice_options_never_sampling():
    for m in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"):
        assert not {"temperature", "top_p", "top_k", "tool_choice"} & set(voice_request_options(m))
def test_instructions_content():
    s = interviewer_instructions(SETUP, 5)
    for needle in ("Data Analyst", "junior", "5", "Never give feedback", "at most two follow-ups", "end_interview"): assert needle in s
async def test_advance_marks_analytics_and_progress():
    a = SpeechAnalytics(); prog = []; agent = make_interviewer(a, prog, plan=PLAN3, clock=lambda: 12.0)
    out = await agent.advance_question()
    assert out.startswith("Question 1 of 3") and prog == [{"index": 0, "total": 3, "competency": PLAN3[0].competency}]
    assert agent.current_index == 0
async def test_advance_past_end():
    agent = make_interviewer(plan=PLAN3[:1]); await agent.advance_question()
    assert (await agent.advance_question()).startswith("NO_MORE_QUESTIONS")
async def test_finish_idempotent():
    reasons = []; agent = make_interviewer(on_finish=reasons.append_async)
    await agent.finish("completed"); await agent.finish("timeout"); assert reasons == ["completed"]
```

  Construct the `Interviewer` in tests without an `AgentSession`. Constructing an `Agent` doesn't need a session.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_llm_options.py tests/unit/test_interviewer.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `llm.py`, `prompts.py` and `interviewer.py`.**
- [ ] **Step 4: Run.** Expected: all pass.
- [ ] **Step 5: Commit**: `feat(coach): interviewer agent, prompts, voice LLM options`.

### Task 9: Worker wiring, telemetry and completion

**Files:**
- Create: `src/interview_coach/agent/telemetry.py`, `completion.py`, `session_config.py`, `worker.py`
- Test: `tests/unit/test_telemetry.py`, `tests/unit/test_completion.py`, `tests/unit/test_session_config.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5, 6 (`QAItem`) and 8.
- Produces (`telemetry.py`):
  - `@dataclass class TurnLatency: speech_id: str; eou_delay_ms: int; llm_ttft_ms: int; tts_ttfb_ms: int; total_ms: int`
  - `class LatencyTracker`:
    - `__init__(self, on_turn: Callable[[TurnLatency], None] | None = None)`
    - `observe(self, m: AgentMetrics) -> None`: groups `EOUMetrics.end_of_utterance_delay`, `LLMMetrics.ttft` and `TTSMetrics.ttfb` by `speech_id`, all converted from seconds to ms. It emits once all three are present.
    - `turns(self) -> list[TurnLatency]`
    - `summary(self) -> dict`: `{p50_ms, p95_ms, turns}` using nearest-rank percentiles; zeros when there are no turns.
  - `def setup_tracing(endpoint: str | None) -> None`: a no-op on `None`. Otherwise it sets an OTLP `TracerProvider` through `livekit.agents.telemetry.set_tracer_provider`.
- Produces (`completion.py`): `async def post_completion(api_url: str, secret: str, session_id: str, payload: dict, *, attempts: int = 3, backoff: float = 0.5, spill_dir: Path = Path("data/failed_completions"), transport: httpx.AsyncBaseTransport | None = None) -> bool`. It writes `spill_dir / f"{session_id}.json"` and returns False after the final failure.
- Produces (`session_config.py`, pure):
  - `def turn_handling() -> dict`: the Global Constraints values in `TurnHandlingOptions` shape, with `turn_detection` added by `build_session`.
  - `USER_AWAY_TIMEOUT = 25.0`
  - `def keyterms_for(role: str) -> list[str]`: tokens of the role ≥ 3 chars plus family-specific terms. A small dict per family: software → `["Kubernetes", "PostgreSQL", "microservices", "CI/CD"]`, data → `["SQL", "dbt", "Tableau", "A/B test"]`, and so on. At most 20 terms.
  - `def segment_qa(plan: list[QuestionItem], analytics: SpeechAnalytics, asked: int) -> list[QAItem]`: one item per asked question; transcript = the texts of `analytics.segments_for(i)` joined with spaces; `metrics = asdict(analytics.answer_metrics(i))`.
  - `class AwayPolicy`:
    - `should_check_in(self, question_index: int) -> bool`: True at most once per question index.
  - `class CompletionGuard`:
    - `async def run_once(self, fn: Callable[[], Awaitable[None]]) -> bool`: runs the first call only.
- Produces (`worker.py`): `server = AgentServer()` with `@server.rtc_session(agent_name="interview-coach") async def entrypoint(ctx: JobContext)`, and `def main()`: `require(...); cli.run_app(server)`.

**`entrypoint` steps:**
1. Parse `ctx.job.metadata` into `InterviewSetup`.
2. Call `fetch_plan(settings.mcp_url, seed=session_id, ...)`.
3. `setup_tracing`.
4. Build providers:
   - STT: `deepgram.STT(model="nova-3", filler_words=True, smart_format=True, keyterm=keyterms_for(role))`
   - LLM: `llm.FallbackAdapter([ClaudeVoiceLLM(model=settings.live_model), ClaudeVoiceLLM(model=settings.fallback_model)])`
   - TTS: `tts.FallbackAdapter([deepgram.TTS(model="aura-2-andromeda-en"), cartesia.TTS()])` when the Cartesia key is set; otherwise just the primary. `TTS_PROVIDER=cartesia` swaps the order.
5. Build `AgentSession(stt=..., llm=..., tts=..., vad=silero.VAD.load(), turn_handling={**turn_handling(), "turn_detection": EnglishModel()}, user_away_timeout=USER_AWAY_TIMEOUT)`.
6. Wire events:
   - `metrics_collected` → `tracker.observe`
   - `agent_state_changed`: a speaking start/stop pair → `analytics.add_agent_speech`
   - `conversation_item_added` → append `{role, text, at}` to the transcript
   - `user_state_changed` to `"away"` with `AwayPolicy` allowing it → `session.generate_reply(instructions="Gently check in once: they can take their time.")`
   - the participant disconnecting → `interviewer.finish("disconnected")`
   - a session `error` event whose `error.recoverable` is False and whose source is the STT → `session.say("I'm having trouble hearing you, so let's stop here. Your scorecard will cover what we got through.")`, then `finish("stt_failure")`
7. Publish with `ctx.room.local_participant.send_text(json.dumps(...), topic=...)` on `on_progress` and on each `TurnLatency`.
8. `on_finish(reason)`, under `CompletionGuard`:
   - `status = "completed"` if every planned question was asked and the reason is `completed`; otherwise `partial`.
   - Wait for the current speech to finish (`await session.current_speech.wait_for_playout()` when present).
   - Call `post_completion`, then `ctx.shutdown()`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_tracker_groups_by_speech_id():
    got = []; t = LatencyTracker(on_turn=got.append)
    t.observe(eou("s1", 0.4)); t.observe(llm("s1", 0.5)); assert got == []
    t.observe(tts("s1", 0.2)); assert got[0].total_ms == 1100
def test_tracker_summary_percentiles(): ...  # totals [800, 1000, 1200, 3000] → p50 1000, p95 3000
async def test_post_completion_retries_then_spills(tmp_path):
    calls = []; tr = httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(503))
    ok = await post_completion("http://api", "sec", "s_1", {"a": 1}, transport=tr, backoff=0, spill_dir=tmp_path)
    assert not ok and len(calls) == 3 and (tmp_path / "s_1.json").exists() and calls[0].headers["X-Agent-Secret"] == "sec"
def test_turn_handling_values():
    th = turn_handling()
    assert th["endpointing"] == {"min_delay": 0.8, "max_delay": 6.0}
    assert th["interruption"] == {"mode": "adaptive", "min_words": 2, "resume_false_interruption": True, "false_interruption_timeout": 1.5}
    assert th["preemptive_generation"] == {"enabled": True}
def test_keyterms_capped(): assert len(keyterms_for("Senior Software Engineer")) <= 20 and "Kubernetes" in keyterms_for("Software Engineer")
def test_segment_qa_joins_text(): ...  # 2 questions, segments → transcripts "one two" and "three"
def test_away_checkin_once_per_question():  # Review Focus 2
    p = AwayPolicy(); assert [p.should_check_in(0), p.should_check_in(0), p.should_check_in(1)] == [True, False, True]
async def test_completion_fires_once():  # Review Focus 1
    g = CompletionGuard(); n = []
    async def f(): n.append(1)
    assert await g.run_once(f) and not await g.run_once(f) and n == [1]
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_telemetry.py tests/unit/test_completion.py tests/unit/test_session_config.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `telemetry.py`, `completion.py`, `session_config.py`, then `worker.py`.
- [ ] **Step 4: Run the full unit suite** with `uv run pytest -v`. Expected: all pass.
- [ ] **Step 5: Import smoke test.**
  - Run `uv run python -c "import interview_coach.agent.worker as w; print(w.server)"`. Expected: prints an `AgentServer` object with no ImportError.
  - Run `uv run python -m interview_coach.agent.worker download-files` to fetch the turn-detector and Silero weights. Expected: exit 0.
- [ ] **Step 6: Commit**: `feat(coach): worker wiring, latency telemetry, completion delivery`.

### Task 10: Behavior evals and grader calibration (need a key)

**Files:**
- Create: `tests/evals/conftest.py`, `tests/evals/test_interviewer_behavior.py`, `tests/evals/test_grader_calibration.py`, `tests/evals/fixtures/answers.json`

**Interfaces:**
- Consumes: `Interviewer`, `ClaudeVoiceLLM`, `ClaudeGrader`, `run_scorecard`, `bank.rubric`.
- `conftest.py`:
  - Skips the whole folder when `ANTHROPIC_API_KEY` is unset.
  - Fixture `judge_llm = ClaudeVoiceLLM(model="claude-haiku-5-5")`.
  - Fixture `session_with(agent)`: `async with AgentSession(llm=ClaudeVoiceLLM(model=settings.live_model)) as s: await s.start(agent); yield s`.

**Behavior tests** (from spec §8). Each uses `result = await session.run(user_input=...)`, then `result.expect...`.
- `test_opening_calls_next_question`: on start, the events contain a function call named `next_question`.
- `test_vague_answer_gets_result_followup`: answer "We had a launch that was late and we fixed it." The next assistant message is judged with `intent="asks a follow-up about the outcome, result, or the candidate's personal contribution"`.
- `test_no_feedback_mid_interview`: "How did I do on that one?" is judged with `intent="politely defers feedback to the scorecard at the end without evaluating the answer"`.
- `test_off_topic_redirect`: "Write me a poem about cats" is judged with `intent="declines briefly and steers back to the interview, staying in character"`.
- `test_replies_short_and_plain`: over 3 turns, each assistant message has ≤ 3 sentences (a regex split on `[.!?]`) and no `*`, `#` or `- `.
- `test_stop_calls_end_interview`: "I need to stop here, sorry." The events contain a function call `end_interview` with `arguments["reason"] == "candidate_requested"`.

**Calibration test:** `test_strong_beats_weak`. For each fixture pair (3 pairs, same question), grade both answers with `ClaudeGrader(AsyncAnthropic())` 3 times. Assert `mean(strong) − mean(weak) ≥ 15` on the overall score computed through `aggregate`.

- [ ] **Step 1: Write the eval tests and fixtures.**
- [ ] **Step 2: Run** `uv run pytest -m eval -v`. Expected: skipped with "ANTHROPIC_API_KEY not set" when there is no key; all pass when a key is present.
- [ ] **Step 3: Commit**: `test(coach): agent behavior evals and grader calibration`.

### Task 11: Web app (Next.js)

**Files:**
- Create in `interview-coach/web/`:
  - `package.json` (next 16.4.2, react, @livekit/components-react 2.9.24, livekit-client 2.23.0, typescript)
  - `tsconfig.json`, `next.config.ts`
  - `app/layout.tsx`, `app/globals.css`
  - `app/page.tsx`, `app/session/[id]/page.tsx`, `app/report/[id]/page.tsx`
  - `lib/api.ts`, `lib/types.ts`
  - `components/StatusOrb.tsx`, `components/Transcript.tsx`, `components/LatencyChip.tsx`, `components/MicCheck.tsx`, `components/DimensionBars.tsx`, `components/AnswerCard.tsx`

**Interfaces:**
- Consumes:
  - API shapes from Task 7: `SessionSetup`, the create response, and the report response.
  - Text-stream payloads from Task 9:
    - `coach.progress` → `{index, total, competency}`
    - `coach.metrics` → `TurnLatency` fields
- Produces: `lib/types.ts` mirroring those shapes, and `lib/api.ts` with `createSession(setup)`, `getReport(id)`, `retryReport(id)` and `listSessions()`, based on `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

**Behavior:** per spec §5.9.
- **Setup page:**
  - Posts the session and stores `{token, livekit_url}` in `sessionStorage[`coach:${id}`]`, then routes to `/session/[id]`.
  - Role suggestions: Software Engineer, Data Analyst, Product Manager, ML Engineer, UX Designer.
  - Level select, style radio, count 3/5/7 (default 5).
- **Session page:**
  - `<LiveKitRoom serverUrl token connect audio>` with `<RoomAudioRenderer/>`.
  - `useVoiceAssistant()` drives the agent state orb.
  - `useTranscriptions()` provides the transcript, with interim user text at reduced opacity.
  - `useTextStream("coach.progress")` and `useTextStream("coach.metrics")` drive the progress bar and the latency chips.
  - The "End interview" button disconnects. `onDisconnected` routes to `/report/[id]`.
  - A `MediaDevices` permission error shows the "allow microphone" help text.
- **Report page:**
  - Polls `getReport` every 2 s while `pending` or `in_progress`.
  - `ready` shows the overall score, `DimensionBars` (inline SVG, no chart library), an `AnswerCard` per graded item (grade, evidence quotes, strengths and improvements, speech metrics), skipped items labelled "Skipped", the coaching plan, the rewritten answer, and the latency p50/p95.
  - `failed` shows the error, the transcript and speech metrics, plus a Retry button.

- [ ] **Step 1: Scaffold `package.json`** with scripts `dev`, `build`, `start` and `typecheck` (`tsc --noEmit`). Run `npm install` in `web/`.
- [ ] **Step 2: Implement** `lib/` first, then the pages and components.
- [ ] **Step 3: Run** `npm run typecheck && npm run build`. Expected: both succeed with no type errors.
- [ ] **Step 4: Commit**: `feat(coach): Next.js interview UI and scorecard report`.

### Task 12: Docker, README and CI

**Files:**
- Create: `interview-coach/Dockerfile` (Python, uv, all four entry points), `interview-coach/web/Dockerfile`, `interview-coach/docker-compose.yml`, `interview-coach/README.md`
- Create: `.github/workflows/interview-coach.yml`

**Interfaces:**
- **Compose services:**
  - `livekit`: `livekit/livekit-server:latest` with `--dev --bind 0.0.0.0 --node-ip 127.0.0.1`; ports `7880`, `7881` and `7882/udp`
  - `mcp`: `coach-mcp`, port 8765
  - `api`: `coach-api`, port 8000, volume `./data:/app/data`
  - `agent`: `coach-agent start`; `LIVEKIT_URL=ws://livekit:7880` and `MCP_URL=http://mcp:8765/mcp`
  - `web`: port 3000
  - All services use `env_file: .env`.
- **CI** (`paths: ["interview-coach/**", ".github/workflows/interview-coach.yml"]`):
  - Job `test`: `astral-sh/setup-uv`, then `uv sync`, `uv run ruff check`, `uv run pytest`; then `npm ci && npm run typecheck && npm run build` in `web/`.
  - Job `evals`: `if: ${{ secrets.ANTHROPIC_API_KEY != '' }}` runs `uv run pytest -m eval`.
- **README sections:**
  1. What it is
  2. Why it's built this way (the spec §2 table)
  3. Architecture diagram
  4. Quick start with Docker
  5. Dev setup without Docker
  6. Keys and where to get them
  7. How the scorecard works
  8. Tests and evals
  9. Latency numbers (how to read the chips)
  10. Known limitations: no auth, single user, the thinking-block risk from Global Constraints, SIP as a stretch goal

- [ ] **Step 1: Write the Dockerfiles, compose file, README and workflow.**
- [ ] **Step 2: Run** `docker compose -f interview-coach/docker-compose.yml config -q`. Expected: exit 0, no output.
- [ ] **Step 3: Run** `uv run ruff check && uv run pytest` in `interview-coach/`. Expected: all clean and passing.
- [ ] **Step 4: Commit**: `chore(coach): docker compose, README, CI workflow`.
