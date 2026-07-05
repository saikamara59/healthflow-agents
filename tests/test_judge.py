import pytest

from evals.translate.judge import JudgeVerdict, judge
from healthflow_agents.contracts import DocumentSection

SECTIONS = [DocumentSection(title="ER", content="ER copay $120, waived if admitted.")]


class _Block:
    def __init__(self, text): self.text = text


class _Resp:
    def __init__(self, text): self.content = [_Block(text)]


class FakeClient:
    """Returns queued responses; records calls."""
    def __init__(self, *texts):
        self._texts = list(texts)
        self.calls = 0
        class _M:
            def create(_self, **kwargs):
                self.calls += 1
                return _Resp(self._texts.pop(0))
        self.messages = _M()


def test_judge_parses_clean_json():
    client = FakeClient(
        '{"faithful": true, "hallucinated": false, "contradicts_gold": false, "rationale": "matches doc"}'
    )
    v = judge(client, SECTIONS, "ER copay?", "It is $120, waived if admitted.", "Your ER copay is $120, waived on admission.")
    assert isinstance(v, JudgeVerdict)
    assert v.faithful is True
    assert v.hallucinated is False
    assert v.contradicts_gold is False
    assert v.rationale == "matches doc"
    assert client.calls == 1


def test_judge_strips_code_fence():
    client = FakeClient(
        '```json\n{"faithful": false, "hallucinated": true, "contradicts_gold": true, "rationale": "invented dental"}\n```'
    )
    v = judge(client, SECTIONS, "Dental?", "Not covered.", "Dental implants are fully covered.")
    assert v.faithful is False
    assert v.hallucinated is True


def test_judge_retries_once_on_bad_json_then_succeeds():
    client = FakeClient(
        "not json at all",
        '{"faithful": true, "hallucinated": false, "contradicts_gold": false, "rationale": "ok"}',
    )
    v = judge(client, SECTIONS, "q?", "gold", "answer")
    assert v.faithful is True
    assert client.calls == 2


def test_judge_raises_after_two_bad_responses():
    client = FakeClient("garbage", "still garbage")
    with pytest.raises(ValueError, match="judge"):
        judge(client, SECTIONS, "q?", "gold", "answer")
