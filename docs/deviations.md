# Deviations from the pre-registered plan

The paper claims a pre-registered design. This file is the index to the record that lets a reader
check that claim rather than take it on trust. The **full log, verbatim and untranslated** (it is
kept in the working language of the project), is at
[`../artifact/configs/deviations.md`](../artifact/configs/deviations.md); the supplementary PDF
reproduces it byte-for-byte alongside an English index.

Three kinds of entry appear there, and the distinction matters when reading the paper:

- **Corrections** — a defect the authors found in their own procedure and fixed. Each names the
  review round that found it. Several were found by independent review of an earlier release of this
  work, and two were defects in the validity gate itself.
- **Registrations** — something done after a design decision had already been made, recorded rather
  than backdated. The two arms of the second experiment that were dropped on pilot evidence are the
  clearest case.
- **Route decisions** — where an experiment was re-scoped rather than completed. The AppWorld
  portability attempt is recorded as a *negative result* with a stated boundary, not as a
  failed validation that has been quietly dropped.

## The convention that governs all of it

A superseded result is **kept beside its replacement**, never overwritten. Where a pre-fix number
appears in an analysis output, both the pre-fix and post-fix files ship. This is why
`results/summary/` contains both `b_validity_pre_r1fix.csv` and `b_validity_r1fix.csv` in the
archives, and why the paper reports the miss in the detector matrix rather than the cleaner summary
that would have hidden it.

## The two entries to read first

If you read only two, read the ones where the pre-registered hypothesis was **contradicted**:

1. The component effects **do not add** — the pre-registered mechanism account predicted they would.
   The paper reports the disagreement rather than reconstructing a story that fits both, and states
   the power at which that contrast is decididable (17 %).
2. The detector set is **not** blind-spot-free. The full suite misses one combination on all three
   targets, and the paper says so in §4.1 rather than reporting the class-level summary that conceals
   it.
