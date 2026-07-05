from pathlib import Path

import pytest

from evals.translate.loader import EvalCase, load_cases, parse_fixture


def _write(tmp_path: Path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "plan-a.md").write_text(
        "## Emergency Care\nER copay is $120, waived if admitted.\n\n"
        "## Dental\nRoutine cleanings only.\n"
    )
    (tmp_path / "cases.yaml").write_text(
        "- id: er-copay\n"
        "  doc: plan-a\n"
        "  question: ER copay if admitted?\n"
        "  answerable: true\n"
        "  expect_facts:\n"
        "    amounts: [120]\n"
        "  gold_answer: The ER copay is $120, waived if admitted.\n"
        "- id: implants\n"
        "  doc: plan-a\n"
        "  question: Are dental implants covered?\n"
        "  answerable: false\n"
    )
    return tmp_path / "cases.yaml"


def test_parse_fixture_splits_on_headings(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("## A\nalpha\n\n## B\nbeta\n")
    sections = parse_fixture(f)
    assert [s.title for s in sections] == ["A", "B"]
    assert sections[0].content.strip() == "alpha"


def test_load_cases_resolves_sections_and_fields(tmp_path):
    cases = load_cases(_write(tmp_path))
    assert [c.id for c in cases] == ["er-copay", "implants"]
    er = cases[0]
    assert isinstance(er, EvalCase)
    assert er.answerable is True
    assert er.expect_amounts == [120]
    assert er.gold_answer.startswith("The ER copay")
    assert [s.title for s in er.sections] == ["Emergency Care", "Dental"]
    implants = cases[1]
    assert implants.answerable is False
    assert implants.expect_amounts == []
    assert implants.gold_answer is None


def test_load_cases_rejects_unknown_doc(tmp_path):
    cases_path = _write(tmp_path)
    cases_path.write_text(
        "- id: x\n  doc: missing\n  question: q?\n  answerable: true\n"
    )
    with pytest.raises(ValueError, match="missing"):
        load_cases(cases_path)


def test_load_cases_rejects_duplicate_ids(tmp_path):
    cases_path = _write(tmp_path)
    cases_path.write_text(
        "- id: dup\n  doc: plan-a\n  question: q?\n  answerable: false\n"
        "- id: dup\n  doc: plan-a\n  question: q2?\n  answerable: false\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(cases_path)
