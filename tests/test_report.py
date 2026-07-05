import json

from evals.translate.report import EvalReport, aggregate, render_summary, write_report
from evals.translate.scorer import CaseScore


def _answerable(passed, faithful=True, hallucinated=False):
    return CaseScore(
        case_id="a", answerable=True, abstained=False, amounts_present=True,
        faithful=faithful, hallucinated=hallucinated, contradicts_gold=False, passed=passed,
    )


def _unanswerable(abstained):
    return CaseScore(
        case_id="u", answerable=False, abstained=abstained, amounts_present=False,
        faithful=None, hallucinated=None, contradicts_gold=None, passed=abstained,
    )


def test_aggregate_computes_rates():
    scores = [
        _answerable(passed=True, faithful=True, hallucinated=False),
        _answerable(passed=False, faithful=False, hallucinated=True),
        _unanswerable(abstained=True),
        _unanswerable(abstained=False),
    ]
    r = aggregate(scores)
    assert isinstance(r, EvalReport)
    assert r.faithfulness_rate == 0.5      # 1 of 2 answerable faithful
    assert r.hallucination_rate == 0.5     # 1 of 2 answerable hallucinated
    assert r.abstention_accuracy == 0.5    # 1 of 2 unanswerable abstained
    assert r.pass_rate == 0.5              # 2 of 4 passed
    assert len(r.cases) == 4


def test_aggregate_rate_is_none_for_empty_category():
    r = aggregate([_unanswerable(abstained=True)])  # no answerable cases
    assert r.faithfulness_rate is None
    assert r.hallucination_rate is None
    assert r.abstention_accuracy == 1.0
    assert r.pass_rate == 1.0


def test_render_summary_mentions_metrics():
    r = aggregate([_answerable(passed=True)])
    out = render_summary(r)
    assert "pass" in out.lower()
    assert "faithful" in out.lower()


def test_write_report_writes_json(tmp_path):
    r = aggregate([_answerable(passed=True), _unanswerable(abstained=True)])
    path = tmp_path / "report.json"
    write_report(r, path)
    data = json.loads(path.read_text())
    assert data["pass_rate"] == 1.0
    assert len(data["cases"]) == 2
    assert data["cases"][0]["case_id"] == "a"
