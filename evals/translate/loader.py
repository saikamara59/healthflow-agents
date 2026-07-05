from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from healthflow_agents.contracts import DocumentSection


@dataclass(frozen=True)
class EvalCase:
    id: str
    sections: list[DocumentSection]
    question: str
    answerable: bool
    expect_amounts: list[int]
    gold_answer: str | None


def parse_fixture(path: Path) -> list[DocumentSection]:
    """Split a fixture markdown file into sections on `## ` headings."""
    sections: list[DocumentSection] = []
    title: str | None = None
    body: list[str] = []
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            if title is not None:
                sections.append(DocumentSection(title=title, content="\n".join(body).strip()))
            title = line[3:].strip()
            body = []
        else:
            body.append(line)
    if title is not None:
        sections.append(DocumentSection(title=title, content="\n".join(body).strip()))
    return sections


def load_cases(cases_path: Path) -> list[EvalCase]:
    """Load cases.yaml and resolve each referenced fixture into sections."""
    cases_path = Path(cases_path)
    fixtures_dir = cases_path.parent / "fixtures"
    raw = yaml.safe_load(cases_path.read_text()) or []

    seen: set[str] = set()
    cases: list[EvalCase] = []
    for entry in raw:
        cid = entry["id"]
        if cid in seen:
            raise ValueError(f"duplicate case id: {cid}")
        seen.add(cid)

        fixture = fixtures_dir / f"{entry['doc']}.md"
        if not fixture.exists():
            raise ValueError(f"case {cid}: fixture not found for doc '{entry['doc']}'")

        answerable = bool(entry["answerable"])
        facts = entry.get("expect_facts") or {}
        cases.append(
            EvalCase(
                id=cid,
                sections=parse_fixture(fixture),
                question=entry["question"],
                answerable=answerable,
                expect_amounts=list(facts.get("amounts", [])),
                gold_answer=entry.get("gold_answer") if answerable else None,
            )
        )
    return cases
