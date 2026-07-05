# TODO

(no outstanding items)

- ~~Convert `redaction/prompt_inputs.py` from frozen dataclasses to Pydantic
  models.~~ Done in v0.2.0. Invariants preserved and now test-enforced
  (tests/test_prompt_inputs.py "Pydantic model invariants" section):
  frozen instances, redaction at construction via a `mode="before"`
  validator, raw text never stored (absent from repr and dumps),
  `redaction_summary` shape unchanged, and — new — AppealPromptInput
  rejects direct `redacted_*` construction so pre-"redacted" text cannot
  bypass the boundary.
