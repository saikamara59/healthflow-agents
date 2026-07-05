# Fixture provenance

These are excerpts of a public Medicare Advantage **Summary of Benefits**
document (public marketing material — no PHI). Sections were extracted from the
real PDF and lightly reformatted into clean markdown for benchmarking; all dollar
figures and conditions are quoted faithfully from the source.

- `humana-gold-plus-h1036-217.md` — **Humana Gold Plus H1036-217 (HMO)**, Gulf
  Coast, FL, plan year **2025**.
  Source: https://content.medicareadvantage.com/2025/Humana-H1036-217-000-SB-EN-2025-SF20240913.pdf
  Retrieved: 2026-06-28.

Note: only a subset of the plan's sections is included (the ones the gold cases
ask about). Topics deliberately left out of the fixture — e.g. fitness/gym
benefits, over-the-counter allowances, cosmetic surgery, and foreign-travel
emergency coverage — are used as `answerable: false` cases to test whether the
agent abstains rather than inventing an answer.
