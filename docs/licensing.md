# Licensing — scope of the MIT grant

The repository's [`LICENSE`](../LICENSE) is plain MIT: it is kept free of any added text so that
GitHub and automated licence scanners classify it correctly.

This file records what that grant **does and does not** cover, because a bare MIT file would
otherwise be read as covering everything in the repository — including two things it cannot.

## Covered by MIT

The software authored for this study:

- the oracle-integrity suite (detectors, adapters, oracle variants, runner);
- the analysis, experiment and checking scripts;
- the packaging, provenance and reproduction tooling.

That includes commercial reuse. No permission is needed.

## Not covered

| Not covered | Why | Governed instead by |
|---|---|---|
| **τ-bench**, under `vendor/tau-bench/` | Vendored third-party code | Its own MIT licence, © 2024 Sierra, which travels with it. Where the two differ, τ-bench's own terms govern that subtree |
| **The data** — frozen per-episode records, adjudication inputs, model-served text | Contains outputs of third-party model services that the authors cannot license unconditionally | [`data_availability.md`](data_availability.md) |
| **AppWorld's protected content** | Its licence permits public redistribution only in encrypted form | Not distributed at all — see [`third_party.md`](third_party.md) |

## If you are reusing

Keep τ-bench's licence and copyright headers intact alongside this one, and read
[`data_availability.md`](data_availability.md) before redistributing anything from `results/` that
originated as model output.
