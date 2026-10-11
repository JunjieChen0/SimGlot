# `results/metadata/`

Provenance for everything under `results/`.

| File | What it is |
|---|---|
| `../summary/` | The **small inputs** the analyses read, and the tables they produced from them. Every file here is either an analysis output or a frozen record small enough to ship |
| `../figures/` | The two figures from the v1.0 manuscript and the scripts that draw them. The EMSE manuscript carries no figures, so these are retained only because the generator scripts are part of the analysis code |
| `../../manifests/provenance.json` | For every **code** file in this repository: its path here, its path in the working tree, the archive role it came from, and its SHA-256 |
| `../../manifests/FINAL_RELEASE_MANIFEST.json` | Which archive backs which experiment and which paper section |

## The rule these files follow

Nothing under `results/` is a copy of a large artifact. The archives hold the per-episode records;
what ships here is (a) the small tables an analysis actually consumes, and (b) the tables the
analyses produce. That keeps the repository reviewable and keeps the version binding meaningful:
`docs/data_availability.md` says where the rest is.

## Regenerating

`python3 artifact/scripts/build_tables.py` rebuilds `summary/table1_variant_necessity.csv` and
`summary/table1_summary.csv` from `summary/b_matrix.csv`, `summary/b_validity.csv` and
`artifact/holdout/mutant_catalog.json`, and prints them next to the numbers in the paper.
