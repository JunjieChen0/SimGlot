# SimGlot

**SimGlot is an empirical study of reliability failures in LLM agent evaluation systems.**

It treats an agent benchmark's evaluation harness — its task suite, its input generator, and above
all its **test oracle**, the reward function that decides pass or fail — as a piece of software, and
audits that software the way software engineering audits anything else: with tests aimed at the
instrument rather than at the thing being measured.

This repository is the artifact for the paper:

> **When Agent Evaluation Becomes Unreliable: An Empirical Study of Oracle Failures and
> Configuration-Dependent Measurement in an LLM Agent Benchmark**
> Junjie Chen, Nanjing University of Science and Technology.
> Submitted to *Empirical Software Engineering*.

---

## What the paper found

Running on **τ-bench** (retail and airline domains) plus a ground-truth-controlled synthetic domain:

1. **An oracle defect, with a minimal reproduction.** The benchmark's reward function resets the
   environment database to build a ground-truth hash and never restores it. The value it *returns*
   is correct, and the benchmark's own runner is unaffected — it becomes a wrong label only for a
   harness that scores an episode *after* the session ends and therefore re-reads an environment
   holding the reference solution. Our harness did exactly that. Across 4,320 episodes the archived
   labels report **4,194** database passes where an independent replay of the recorded tool calls
   gives **2,883**; measured success falls from **94.3 % to 65.5 %**.

2. **An oracle-integrity auditing approach, with its sensitivity and specificity measured.** Eight
   checks in two families — five state-integrity invariants and three known-answer controls — plus a
   fault-injection battery of seven defect classes. Over 21 variants × 3 targets the full suite
   detects **54 of 57** on the primary denominator, misses exactly one combination on all three
   targets, and four of the eight checks are load-bearing while four are redundant.

3. **A configuration-dependent reliability effect.** Changing the language of the apparatus leaves
   aggregate success unchanged but moves the rate at which one agent's trajectory degenerates by a
   factor of two to ten. All three documents the agent reads carry a protective effect and the
   effects do not add.

**Main contributions:** oracle integrity auditing for LLM agent benchmarks · fault injection and
evaluation-reliability analysis · a configuration-dependent reliability study · a reproducible
artifact package with explicit version binding.

---

## Quick start

```bash
git clone https://github.com/JunjieChen0/SimGlot.git
cd SimGlot
bash artifact/scripts/reproduce.sh
```

No API key, no network access and no model client are needed for the steps that ship here. The
oracle-integrity suite makes **zero** model calls.

`reproduce.sh` runs what can run from this repository alone and says what cannot, rather than
failing partway through or silently skipping. `--list` shows the plan; `--fast` runs only the
environment check. Two tiers, and what `exit 0` does and does not mean, are in
[docs/reproduction.md](docs/reproduction.md).

**Worth doing first:** `python3 artifact/scripts/build_tables.py` recomputes the paper's Table 1
from the data in this repository in about a second, and prints it next to the numbers it produces.
If the two ever disagree, the paper is wrong — not the script.

---

## Repository layout

```
SimGlot/
├── README.md
├── LICENSE                     MIT, for the code
├── CITATION.cff
├── paper/
│   ├── manuscript.pdf          the submission version
│   └── supplementary.pdf       the five supplementary documents, merged
├── artifact/
│   ├── oracle_audit/           ← the core contribution
│   ├── holdout/                the 21-variant fault-injection battery and the differential probes
│   ├── gates/                  the four gates: validity regression, order/cache counterexample,
│   │                           scoring regression, source binding
│   ├── experiments/            E1 / E2 / E3 / the scoring correction
│   ├── analysis/               the analyses that produce the paper's tables and figures
│   ├── harness/                the v1.0 evaluation harness (the half that scores separately)
│   ├── configs/                task identifiers, model settings, pre-registrations, deviations
│   └── scripts/                reproduce.sh · build_tables.py · verify_environment.py
├── manifests/                  ← version identity
│   ├── FINAL_RELEASE_MANIFEST.json
│   ├── checksums.sha256
│   ├── provenance.json         every code file here, and where in the archives it came from
│   └── versions.md
├── docs/
│   ├── reproduction.md         how to run it, and what each tier proves
│   ├── data_availability.md    what is released, and the two caveats
│   ├── limitations.md          where these results stop
│   ├── deviations.md           every departure from the pre-registered plan
│   └── third_party.md          third-party licences and redistribution boundaries
├── vendor/tau-bench/           the benchmark, MIT (© 2024 Sierra); see the note below
└── results/
    ├── summary/                the small inputs the analyses read, and the tables they produced
    ├── figures/
    └── metadata/
```

### Where to look first

- **The core contribution** — [`artifact/oracle_audit/`](artifact/oracle_audit/). The suite runs from
  one command and needs nothing but this repository.
- **How a table is generated** — [`artifact/scripts/build_tables.py`](artifact/scripts/build_tables.py)
  and [`artifact/analysis/scripts/`](artifact/analysis/scripts/). The scripts ship, not only the CSV.
- **Which revision produced which number** —
  [`manifests/FINAL_RELEASE_MANIFEST.json`](manifests/FINAL_RELEASE_MANIFEST.json).

---

## Version binding

Every number in the paper comes from exactly one of four frozen archives:

| Role | What it backs |
|---|---|
| `v1.0` | the main matrix (4,320 episodes) and the scorer-pollution correction |
| `S2` | the oracle-audit suite, E1 (3,240 cells), E2 (1,200 cells), E3 (212 items) |
| `enhancement` | the 21-variant battery, the detector ablations, the power analysis, the portability attempt |
| `v1.0-anon` | the double-blind copy of `v1.0` |

`manifests/FINAL_RELEASE_MANIFEST.json` maps each archive to the experiments and paper sections it
backs; `manifests/checksums.sha256` records its SHA-256. The archives themselves total 232 MB and
are deposited at Zenodo — they are **not** in this repository, on purpose
([docs/data_availability.md](docs/data_availability.md)).

`manifests/provenance.json` closes the gap between the two: for every code file in this repository it
records the working-tree path and the archive role it came from, so *"is this the code that produced
the paper?"* has a checkable answer rather than a reassuring one. The code files here are
**byte-identical** to their sources; nothing was patched to fit this layout — the layout is adapted
around them instead, which is what `reproduce.sh` spends its first step doing.

---

## What is deliberately *not* here

| Not here | Why |
|---|---|
| The four frozen archives (232 MB) | On Zenodo. GitHub is for code and documentation; the data has a DOI |
| Model-served episode transcripts | They contain outputs of third-party model services — see [docs/data_availability.md](docs/data_availability.md) |
| AppWorld's task data | Its licence permits redistribution only in encrypted form. We ship the adapter and the findings, and report no detection rate for that benchmark |
| `historical_trajectories/` from vendored τ-bench | 50 MB of example trajectories, not needed to run anything here |
| Any API key or credential | The build that produced this repository aborts if one appears |

**On the vendored benchmark.** `vendor/tau-bench/` **is** included, because the audit cannot run
without it; it is MIT (© 2024 Sierra) and keeps its own `LICENSE`. It is **not** vanilla upstream:
our copy carries two changes, both ours, documented in the manuscript — a `try/finally` restoration
added *after* the main matrix had run and used to produce no number in the paper, and a bilingual
output-synonym list in this study's scoring wrapper. A reviewer comparing against Sierra's repository
should expect those two differences and nothing else.

---

## Licence

- **Code: MIT** — [`LICENSE`](LICENSE), kept as plain MIT so that automated licence detection reads
  it correctly. The scope of the grant — what it does *not* cover — is in
  [`docs/licensing.md`](docs/licensing.md).
- **Data: not MIT** — [`docs/data_availability.md`](docs/data_availability.md). The frozen records may
  be used and redistributed for research with attribution; large-scale redistribution or commercial
  use of the episode records should be requested first, because they contain third-party model output.
- **Third-party components** — [`docs/third_party.md`](docs/third_party.md).

## Citation

See [`CITATION.cff`](CITATION.cff). If you use the **data** rather than the code, cite the Zenodo DOI
recorded there rather than this repository — the repository changes, the DOI does not.
