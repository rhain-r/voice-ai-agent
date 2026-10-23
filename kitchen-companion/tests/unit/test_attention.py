import pytest

from kitchen_companion.pipeline.attention import STOP_WORDS, AttentionConfig, Decision, decide

CFG = AttentionConfig()


def d(text, *, now=100.0, window_open_until=0.0, button_armed=False, bot_speaking=False, cfg=CFG) -> Decision:
    return decide(
        text,
        now=now,
        window_open_until=window_open_until,
        button_armed=button_armed,
        bot_speaking=bot_speaking,
        cfg=cfg,
    )


@pytest.mark.parametrize(
    "text,rest",
    [
        ("Chef, next", "next"),
        ("hey chef what's next", "what's next"),
        ("OK Chef.", ""),
        ("okay chef, how much garlic?", "how much garlic?"),
        ("Yo chef! next", "next"),
        ("chef", ""),
        ("  CHEF next step", "next step"),
        ("hi chef, set a timer", "set a timer"),
    ],
)
def test_wake_variants(text, rest):
    out = d(text)
    assert out == Decision(engaged=True, text=rest, reason="wake")


@pytest.mark.parametrize(
    "text",
    ["pass me the chef's knife", "the chef said add salt", "chef's kiss", "chefs are busy", "Chef’s special"],
)
def test_wake_word_must_lead(text):  # Review Focus 1
    out = d(text)
    assert not out.engaged and out.reason == "not_addressed" and out.text == text


def test_followup_window_edges():
    assert d("how much garlic", now=108.0, window_open_until=108.0) == Decision(
        True, "how much garlic", "followup"
    )
    assert d("how much garlic", now=108.01, window_open_until=108.0).reason == "not_addressed"


def test_button_engages_once_text_kept():
    out = d("How Much Garlic?", button_armed=True)
    assert out == Decision(True, "How Much Garlic?", "button")
    assert d("How Much Garlic?", button_armed=False).engaged is False


def test_stop_word_only_while_bot_speaking():
    for word in STOP_WORDS:
        assert d(word, bot_speaking=True) == Decision(True, word, "stop_word")
        assert d(word.capitalize() + ".", bot_speaking=True).reason == "stop_word"
        assert d(word, bot_speaking=False).reason == "not_addressed"
    assert d("stop please", bot_speaking=True).reason == "stop_word"
    assert d("stop adding salt", bot_speaking=True).reason == "not_addressed"


def test_overheard():
    out = d("did you call your mom back")
    assert out == Decision(False, "did you call your mom back", "not_addressed")


def test_empty():
    assert d("") == Decision(False, "", "empty")
    assert d("   ", button_armed=True).reason == "empty"


def test_custom_wake_phrase():
    cfg = AttentionConfig(wake_phrase="sous")
    assert d("sous, next", cfg=cfg) == Decision(True, "next", "wake")
    assert d("chef, next", cfg=cfg).engaged is False


def test_multi_word_wake_phrase():
    cfg = AttentionConfig(wake_phrase="sous chef")
    assert d("hey sous chef, next", cfg=cfg) == Decision(True, "next", "wake")
