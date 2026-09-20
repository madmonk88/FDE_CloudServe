# Fitted artefacts

These four files are the output of the tuning scripts, committed so that a
clean checkout reproduces the same behaviour without needing to re-fit.

| File | Produced by | What it holds |
|---|---|---|
| `taxonomy.json` | `python -m scripts.build_taxonomy` | the 22 intent categories, derived from the labels in the development set |
| `routing_policy.json` | `python -m scripts.derive_policy` | the never-automate and high-risk intents recovered from the data |
| `answerability.json` | `python -m scripts.tune_answerability` | intent priors and the fitted logistic weights |
| `answerability_tuning.json` | `python -m scripts.tune_answerability` | the threshold sweep and the three candidate operating points |

Copy them into `storage/` on a fresh checkout, or just re-run the scripts —
they are deterministic given the same data.

**Re-run `tune_answerability` on a machine where the embedding model
downloads.** These were fitted with lexical-only retrieval because the
build environment could not reach the model host, and the weights and the
threshold will both change once dense retrieval is available.
