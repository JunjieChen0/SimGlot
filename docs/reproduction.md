# Reproduction

Two tiers. The first runs from this repository alone; the second needs the frozen archives.

---

## Tier 1 — everything that runs from this repository

```bash
bash artifact/scripts/reproduce.sh
```

No network, no API key, no model client. The oracle-integrity suite makes **zero** model calls, and
`reproduce.sh` refuses to start if a model key is present in the environment — so a run that claims
to be offline cannot quietly become online.

| Step | What it does | Wall clock |
|---|---|---|
| 0 | `verify_environment.py` — Python version, dependencies, and whether the environment carries a model key | seconds |
| 1 | Builds a scratch workspace in the layout the frozen scripts expect (see below) | seconds |
| 2 | `artifact/oracle_audit/run_audit.py` — the defect-class × detector matrix on two targets | **~10 min** |
| 3 | The four gates: validity regression, order/cache counterexample, scoring regression | minutes |
| 4 | `artifact/scripts/build_tables.py` — recomputes the paper's Table 1 and the detector ablations | **a second** |

`--list` prints this plan without running it. `--fast` runs step 0 only.

### What `exit 0` means here, and what it does not

`exit 0` means **the analyses that can be computed from this repository reproduce**. It does *not*
mean the paper is reproduced: three of the four experiments need per-episode records that live in the
archives, and those are not here. The script says so at the end rather than letting a green run stand
in for a stronger claim — the same distinction the paper draws between *computation* and *provenance*
when it reports source-verification status.

### Why there is a scratch directory

The code here is **byte-identical** to the code that produced the paper
([`manifests/provenance.json`](../manifests/provenance.json) records the hash of each file and where
it came from). Those scripts resolve their paths relative to the original working tree, so
`reproduce.sh` reconstructs that layout under `$SIMGLOT_SCRATCH` rather than patching the scripts.
Adapting the code to a new layout would have been easier and would have broken the one claim that
matters — that what runs here is what ran then.

Set `SIMGLOT_SCRATCH=/some/dir` to keep the workspace for inspection; otherwise it is removed.

---

## Tier 2 — the experiments that need the archives

Get the archives first ([`data_availability.md`](data_availability.md)), then:

```bash
python3 artifact/scripts/verify_freeze.py --packages <dir holding the four archives>
python3 artifact/scripts/build_release_manifest.py --check
```

The first checks each archive against its recorded SHA-256 and exits non-zero on any mismatch; the
second cross-checks the two manifests against each other. Both must pass before you trust a
downstream number.

Then, per experiment:

| Experiment | Command | Where it runs |
|---|---|---|
| E1 component ablation (3,240 cells) | `python3 swe/analyze_e1_full.py` | inside the S2 archive, `sqj/` |
| E2 cross-domain (1,200 cells) | `python3 swe/analyze_e2_full.py` | inside the S2 archive, `sqj/` |
| The whole S2 side in one run | `bash swe/reproduce_s2.sh` | inside the S2 archive, `sqj/` |
| Scorer-pollution replay (4,320 episodes) | `bash scripts/offline_repro.sh` | inside the v1.0 archive, `simglot/` |
| E3 adjudication inputs | `python3 evidence/e3_inputs/build_manifest.py --check` | inside the enhancement archive |

Their outputs are already in [`../results/summary/`](../results/summary/), so you can check the
paper's numbers without running them — and then run them to confirm the numbers did not come from
somewhere else.

**E3's adjudication is not re-runnable.** It was a paid model call that already happened. What the
package contains is its inputs (212 items, de-identified) and its outputs; the reproduction recomputes
the agreement statistics, not the adjudication.

---

## Byte-reproducibility

The analyses are deterministic and recomputable from the frozen records. The **PDFs are not
byte-reproducible**: the LaTeX engine writes a build timestamp and a document identifier into every
file it produces. Compare content, not hashes, for anything under `paper/`. If you need to bind the
published PDF to a source, bind it to a hash of the source.
