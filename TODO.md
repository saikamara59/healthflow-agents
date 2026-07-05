# TODO

- **Convert `redaction/prompt_inputs.py` from frozen dataclasses to Pydantic
  models.** Deliberately NOT done during the port — the frozen-dataclass
  PromptInput pattern (InitVar raw text, redaction in `__post_init__`,
  `object.__setattr__` reassignment) moved verbatim so behavior deltas stay
  attributable to the refactor only. A Pydantic conversion should preserve:
  frozen/immutable instances, redaction at construction time, raw text never
  stored, the `redaction_summary` property shape
  (`{"count": int, "types": [str, ...]}`), and the static
  `test_no_raw_prompt_path.py` guarantee.
