# Limitations

The paper's Threats to Validity section is the authoritative statement; this file is a short index
to the ones a reuser of the artifact most needs to know before building on it.

## The evidence is bounded, and the boundary is measured rather than assumed

- **One benchmark, completed.** The audit finished on τ-bench (retail and airline), plus a
  synthetic domain written from scratch. Those are three *targets*, but the first two are two task
  domains of **one scoring implementation** — not two independent frameworks.
- **A second framework was attempted and did not transfer.** The AppWorld portability attempt is
  reported as a **negative result**: the reference terminal state its positive control needs cannot
  be reconstructed by an external harness from the framework's recorded API-call log. No detection
  rate is reported for it, because none could be estimated.
- **The detector suite is not blind-spot-free.** The full suite misses one combination on all three
  targets: an oracle that swallows an exception raised inside itself, so that INV-4 records the
  probed path as *not applicable* rather than as a violation.
- **The defect battery is author-constructed.** Every variant was written by the authors, so the
  detection figures are a conditional property of *this battery*, not a detection rate for unknown
  defects.

## The measurement, not just the measurement's subject

- **Collapse is an operational definition**, mechanical and reproducible but not a natural kind: a
  maximal run of at least five consecutive reply steps each spending at most two completion tokens
  with no tool call. It is defined on the agent's token counts, which are not a language-neutral unit
  of text.
- **The independent adjudication is a language model, not a person.** The reported 98.1 % is
  agreement with the mechanical criterion, not accuracy against a human reference, and the sample is
  the archive's positives plus matched negatives rather than a draw from a deployment distribution.
- **The component ordering is an observation, not a finding.** The arms come from different run
  periods, the provider exposes no immutable model version, and a power analysis on this design puts
  the 1.11 pp contrast at **17 %** power. It is undecidable at this resolution, and the paper says so
  rather than resolving it.

## What the reuser should not assume

- **The cross-domain reversal is not a mechanism.** Two domains, each changing task set, tool surface
  and base rate together, cannot separate a configuration property from a language × domain
  interaction. What it rules out is that Chinese makes an agent worse or better.
- **Nothing here generalises across providers.** All models came from one provider; the provider
  exposes no deterministic seed, and at temperature zero the same request gives different
  trajectories, so a single run is not evidence anywhere in this work.
- **`gate` counts only what it can see.** The provenance checks report a status per source and count
  as verified only a source whose file was found *and* whose hash matched. An absent archive is
  reported as absent. Reading "no failures reported" as "everything verified" is the mistake these
  checks exist to prevent.
