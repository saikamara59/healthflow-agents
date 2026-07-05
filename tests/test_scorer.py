import pytest

from evals.translate.judge import JudgeVerdict
from evals.translate.loader import EvalCase
from evals.translate.runner import AgentRun
from evals.translate.scorer import CaseScore, detect_abstention, score
from healthflow_agents.contracts import DocumentSection

SECTIONS = [DocumentSection(title="ER", content="copay $120")]


def _case(answerable, amounts=(), gold="$120"):
    return EvalCase(
        id="c", sections=SECTIONS, question="q?", answerable=answerable,
        expect_amounts=list(amounts), gold_answer=gold if answerable else None,
    )


def test_detect_abstention_true_on_markers():
    assert detect_abstention("That is not in the document.") is True
    assert detect_abstention("The document doesn't contain that information.") is True


def test_detect_abstention_false_on_real_answer():
    assert detect_abstention("Your ER copay is $120, waived if admitted.") is False


def test_unanswerable_passes_when_agent_abstains():
    run = AgentRun(_case(False), "That isn't in the document.")
    s = score(run, None)
    assert isinstance(s, CaseScore)
    assert s.abstained is True
    assert s.passed is True
    assert s.faithful is None  # judge not run for unanswerable


def test_unanswerable_fails_when_agent_invents_answer():
    run = AgentRun(_case(False), "Dental implants are fully covered.")
    s = score(run, None)
    assert s.abstained is False
    assert s.passed is False


def test_answerable_passes_when_amounts_present_and_judge_clean():
    run = AgentRun(_case(True, amounts=[120]), "Your ER copay is $120.")
    verdict = JudgeVerdict(faithful=True, hallucinated=False, contradicts_gold=False, rationale="ok")
    s = score(run, verdict)
    assert s.amounts_present is True
    assert s.passed is True


def test_answerable_fails_when_amount_missing():
    run = AgentRun(_case(True, amounts=[120]), "Your ER copay is some dollars.")
    verdict = JudgeVerdict(faithful=True, hallucinated=False, contradicts_gold=False, rationale="ok")
    s = score(run, verdict)
    assert s.amounts_present is False
    assert s.passed is False


def test_answerable_fails_on_hallucination():
    run = AgentRun(_case(True, amounts=[120]), "Your ER copay is $120 and dental is free.")
    verdict = JudgeVerdict(faithful=False, hallucinated=True, contradicts_gold=False, rationale="invented dental")
    s = score(run, verdict)
    assert s.passed is False


def test_answerable_with_no_expected_amounts_is_vacuously_present():
    run = AgentRun(_case(True, amounts=[]), "Cleanings are covered once a year.")
    verdict = JudgeVerdict(faithful=True, hallucinated=False, contradicts_gold=False, rationale="ok")
    s = score(run, verdict)
    assert s.amounts_present is True
    assert s.passed is True


def test_detect_abstention_false_on_legitimate_negation():
    # "does not contain" in a real answer must NOT be read as abstention
    assert detect_abstention("Your plan does not contain a separate deductible.") is False


def test_detect_abstention_true_on_does_not_include_any_information():
    # real agent phrasing observed in the live benchmark
    assert detect_abstention("The document does not include any information about cosmetic surgery.") is True
    assert detect_abstention("This benefit is not mentioned anywhere in the plan.") is True


def test_detect_abstention_false_on_plan_does_not_include_benefit():
    # "does not include" without "any information" must stay a real answer
    assert detect_abstention("Your plan does not include a separate Part D deductible.") is False


def test_answerable_without_verdict_raises():
    run = AgentRun(_case(True, amounts=[120]), "Your ER copay is $120.")
    with pytest.raises(ValueError, match="requires a judge verdict"):
        score(run, None)
