# Third-party licences and redistribution boundaries

The authors' own code is **MIT** ([`LICENSE`](LICENSE)); the data is under a separate statement
([`DATA_TERMS.md`](DATA_TERMS.md)). The components below
carry their own terms, and those terms are not ours to change. Each row was checked against
the component's own licence file or its published terms, not assumed.

| Component | Where it lives | Licence (as found) | In this package |
|---|---|---|---|
| **τ-bench** (vendored) | `simglot/vendor/tau-bench/` inside the v1.0, S2 and enhancement archives | **MIT**, Copyright © 2024 Sierra | Redistributed, with its `LICENSE` and copyright headers intact |
| **AppWorld** — unprotected code | not shipped | **Apache-2.0** | Not shipped; version, source and fingerprint recorded only |
| **AppWorld** — protected content (task data, apps, tests; encrypted bundles) | not shipped | **Apache-2.0 plus an added condition**: any public redistribution of the content or of derivatives must also be in an encrypted format | **Not shipped in plaintext.** The package carries the adapter, the applicability findings and the version fingerprint, and reports no detection rate for this benchmark |
| **sn-jnl** LaTeX class and bibliography styles | the manuscript directory, `paper/template/` (with its own `PROVENANCE.md` and `SHA256SUMS`) | **LPPL 1.3c** (declared in the class file header) | Redistributed with the paper source |
| **Python dependencies** (numpy, scipy, statsmodels, pandas, sqlmodel, …) | not shipped | their own licences | Not shipped; versions recorded |
| **Model outputs** in the archived episodes | inside the frozen records | governed by the serving providers' terms | Shipped as frozen records; **not** represented as unconditionally redistributable (see `DATA_TERMS.md`) |

## Why AppWorld is present as a negative result and not as data

AppWorld was chosen as the second, independently implemented framework for the portability
check because its public train/dev tasks carry complete ground truth
(`solution.py`, `api_calls.json`, `evaluation.py`) and the oracle audit itself makes **no
model calls and needs no network**. Being usable is not the same as being redistributable:
the protected content is encrypted in the distribution and its licence permits public
redistribution only in encrypted form.

So the package takes the position that follows from that: **adapter, findings and version
fingerprint travel; the data does not.** The paper reports the attempt as a negative result
with no detection rate, which is the only honest reading of an experiment whose positive
control could not be reconstructed.

## Verifying the boundary for yourself

The enhancement archive's packaging script enforces this rather than trusting it: assembly
aborts if any credential file, key-shaped string, or AppWorld plaintext content reaches the
staged tree. You can re-run it:

```bash
cd simglot-enhancement-final
bash release/package_enhancement.sh
```

It runs the content gates, including the AppWorld plaintext check, before it packs anything.
