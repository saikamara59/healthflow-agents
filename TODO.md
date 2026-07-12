# TODO

- **Remaining PHI-redaction recall gaps** — street addresses, MRN-labeled
  values, and dates without a DOB-style label pass through unredacted.
  Documented as residual risk in `PHIRedactor`'s docstring and pinned as
  strict-xfail cases in `tests/redaction/test_redaction_corpus.py`
  (`GAP_CASES`) — fixing one flips its test. Bare 10-digit numbers are a
  deliberate non-goal (NPIs share the shape and pass through by design).

- **X12 835 (ERA) parsing** — `tools/x12_835.py` is a NotImplementedError
  stub marking the production ingestion path for provider-side denials
  (CLP loops, CAS/CARC adjustment segments, RARC remark codes, payer
  companion-guide quirks). The simplified CSV/JSON format in
  `tools/remittance_parser.py` stands in until it lands.

- ~~Convert `redaction/prompt_inputs.py` from frozen dataclasses to Pydantic
  models.~~ Done in v0.2.0. Invariants preserved and now test-enforced
  (tests/test_prompt_inputs.py "Pydantic model invariants" section):
  frozen instances, redaction at construction via a `mode="before"`
  validator, raw text never stored (absent from repr and dumps),
  `redaction_summary` shape unchanged, and — new — AppealPromptInput
  rejects direct `redacted_*` construction so pre-"redacted" text cannot
  bypass the boundary.
