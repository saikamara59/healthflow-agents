"""Batch insights agent — a short narrative over one batch's aggregates.

Input is `BatchAggregates`: counts, dollars, and enum-keyed rollups only. No
free text reaches this prompt, so the PHI-redaction boundary is untouched by
construction and no `phi_redacted` event is emitted (ADR 0001). CARC codes
arrive bare and are enriched here from the package's curated DenialCodeDB, so
hosts stay thin and insight quality never depends on host-side lookups.

The output contract — exactly three sections, ~350 words, the host renderer's
markdown subset — lives in prompts/batch_insights.md. `DRY_RUN_NARRATIVE`
below is a format-true sample of it, exported for the host's dry-run client
and demo seed; shipping both in one tag keeps the placeholder from drifting
away from the real format.
"""
from typing import Any

from healthflow_agents.contracts import BatchAggregates
from healthflow_agents.core.base import AgentBase
from healthflow_agents.core.client import extract_text
from healthflow_agents.core.models import CLAUDE_MODEL_SONNET
from healthflow_agents.tools.denial_codes import DenialCodeDB

MAX_TOKENS = 1024

#: The three mandated section headings, in order. The prompt mandates them and
#: DRY_RUN_NARRATIVE demonstrates them; tests hold both to this one list.
INSIGHTS_SECTION_HEADINGS = (
    "What's driving denials",
    "Payer patterns",
    "What to fix upstream",
)

#: Format-true placeholder narrative for dry runs and the public demo. The
#: opening line labels it as a placeholder so a reader can never mistake it for
#: an analysis of their own batch.
DRY_RUN_NARRATIVE = """**Dry run — sample insights. No batch was analyzed and no figures below are real.**

## What's driving denials

Two thirds of this batch denied for missing or malformed claim information (CARC CO-16) — data the payer needed at submission and did not get. That is a clerical failure, not a coverage dispute, and it is the most recoverable category on the list: most of these claims can be corrected and resubmitted rather than argued.

The remainder split across coding-consistency and timely-filing denials. Nineteen claims are already past their appeal deadline and another twelve fall due within the week, so the working order matters as much as the argument.

## Payer patterns

**Aetna** accounts for just over half the denied dollars while representing well under half the claims — its denials skew toward the practice's higher-value procedures. Almost all of them are the same missing-information denial, which points at one intake field rather than a payer policy shift.

**UnitedHealthcare** denials are lower-value and more varied, and a quarter of them were dismissed as correctly denied on review. That mix suggests the practice is appealing some UnitedHealthcare claims it should be writing off.

## What to fix upstream

- Make the fields driving CO-16 required at intake, before the claim can be released — this alone addresses the largest share of the batch.
- Route the highest-value payer's claims through a pre-submission check, given the dollar concentration there.
- Work the overdue and due-this-week appeals first; deadline pressure, not denial value, should set the queue order.
- Revisit the dismissal criteria for the lower-value payer, so staff time goes to appeals worth filing."""


class BatchInsightsAgent(AgentBase):
    """Turns Batch Aggregates into the Batch Insights narrative."""

    # Sonnet, hardcoded: this is inference over aggregates — root causes,
    # payer patterns, prevention recommendations — not Haiku-tier narration of
    # results a tool already computed. See tests/test_model_tiering.py.
    model = CLAUDE_MODEL_SONNET
    agent_name = "batch_insights"
    prompt_file = "batch_insights.md"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.code_db = DenialCodeDB()

    def generate_insights(self, aggregates: BatchAggregates) -> str:
        """Write the markdown narrative for one batch.

        Raises:
            ValueError: the model returned nothing, or its output was cut off
                at the token ceiling. A degenerate narrative is never returned
                as a success — the host maps the exception to its failed state.
            Exception: SDK and network errors propagate untouched.
        """
        with self.invocations(
            agent=self.agent_name, event_type="generate_insights", model=self.model
        ) as inv:
            user_prompt = self._build_prompt(aggregates)

            self.audit.log("tool_called", {"tool": "claude_api", "model": self.model})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Defensive: canned clients need not model stop_reason at all.
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise ValueError(
                    "Batch insights response was truncated at the token ceiling"
                )

            narrative = extract_text(response).strip()
            if not narrative:
                raise ValueError("Batch insights response was empty")

            self.audit.log("insights_generated", {"length": len(narrative)})
            inv.details = {
                "length": len(narrative),
                "records": aggregates.totals.records,
                "payers": len(aggregates.by_payer),
                "carc_codes": len(aggregates.by_carc),
            }
            return narrative

    def _build_prompt(self, aggregates: BatchAggregates) -> str:
        """Render the aggregates as the user message. Deterministic — pinned
        by the golden in tests/goldens/batch_insights.json."""
        totals = aggregates.totals
        deadlines = aggregates.deadlines

        lines = [
            "Write the batch insights narrative for the batch below.",
            "",
            "## Batch totals",
            "",
            f"- Denied claims: {totals.records}",
            f"- Billed amount: {_dollars(totals.billed_amount)}",
            f"- Appeals drafted: {totals.drafted}",
            f"- Appeals submitted: {totals.submitted}",
            f"- Appeals failed: {totals.failed}",
            f"- Claims dismissed: {totals.dismissed}",
            f"- Service dates: {_service_dates(aggregates)}",
            "",
            "## Denials by payer",
            "",
        ]
        lines.extend(
            [
                f"- {payer.payer}: {payer.records} claims, "
                f"{_dollars(payer.billed_amount)} billed"
                for payer in aggregates.by_payer
            ]
            or ["- None recorded"]
        )

        lines += ["", "## Denials by CARC code", ""]
        lines.extend(
            [
                f"- {self._describe_carc(carc.carc_code)}: {carc.records} claims, "
                f"{_dollars(carc.billed_amount)} billed"
                for carc in aggregates.by_carc
            ]
            or ["- None recorded"]
        )

        lines += [
            "",
            "## Appeal deadline pressure",
            "",
            f"- Overdue: {deadlines.overdue}",
            f"- Due within 7 days: {deadlines.due_within_7_days}",
            f"- Due in 7 to 30 days: {deadlines.due_7_to_30_days}",
            f"- Due beyond 30 days: {deadlines.due_beyond_30_days}",
            f"- No deadline on file: {deadlines.unknown}",
            "",
            "## Dismissals by reason",
            "",
        ]
        lines.extend(
            [
                f"- {reason}: {count}"
                # Sorted: dict order is the host's, and the prompt must not
                # vary between two runs over equal aggregates.
                for reason, count in sorted(aggregates.dismissals_by_reason.items())
            ]
            or ["- None recorded"]
        )

        return "\n".join(lines)

    def _describe_carc(self, carc_code: str) -> str:
        """`CO-16 (description)` when the code is in the curated DB, else the
        bare code — an unknown code is never given an invented meaning."""
        entry = self.code_db.lookup(carc_code)
        if entry is None:
            return carc_code
        return f"{carc_code} ({entry['description']})"


def _dollars(amount: float) -> str:
    return f"${amount:,.2f}"


def _service_dates(aggregates: BatchAggregates) -> str:
    if aggregates.service_date_start is None or aggregates.service_date_end is None:
        return "not recorded"
    return (
        f"{aggregates.service_date_start.isoformat()} to "
        f"{aggregates.service_date_end.isoformat()}"
    )
