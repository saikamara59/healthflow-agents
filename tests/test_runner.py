from evals.translate.loader import EvalCase
from evals.translate.runner import AgentRun, run_case
from healthflow_agents.contracts import DocumentSection


class FakeAgent:
    def __init__(self, answer): self.answer = answer; self.seen = None
    def translate(self, sections, question):
        self.seen = (sections, question)
        return self.answer, [s.title for s in sections]


def test_run_case_invokes_agent_and_keeps_answer():
    case = EvalCase(
        id="c1",
        sections=[DocumentSection(title="ER", content="copay $120")],
        question="ER copay?",
        answerable=True,
        expect_amounts=[120],
        gold_answer="$120",
    )
    agent = FakeAgent("Your ER copay is $120.")
    run = run_case(agent, case)
    assert isinstance(run, AgentRun)
    assert run.case is case
    assert run.answer == "Your ER copay is $120."
    assert agent.seen[1] == "ER copay?"
