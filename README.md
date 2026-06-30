# DAI 2026 AI Paper Track Author Kit v0.1

This official kit helps authors and AI assistants prepare the two files required for OpenReview:

1. `paper.pdf`
2. `arm-bundle.zip`

Do **not** upload this whole kit. Use it locally to create a `submission-packet/` containing only those two files.

## README vs. Assistant Prompt

Keep both files in the kit:

- `README.md` is the human-readable quickstart, upload contract, policy reminder, and command reference. It should stay useful even if an author prepares the packet without an AI assistant.
- `author-assistant-prompt.md` is a copy/paste task prompt for Codex or another coding assistant. It converts this README and the CFP rules into an operational checklist.

The prompt intentionally tells the assistant to read this README first. If you keep only the prompt, human authors lose the short public instructions and the validator/packaging commands become harder to find.

## If You Are the Human Author

Give your AI assistant:

- this unzipped Author Kit folder,
- your draft `paper.pdf`,
- the project/code/data/artifact folders that support the paper,
- any agent traces, prompts, logs, configs, or experiment outputs,
- the intended title, abstract, keywords, AI contributor name, and human OpenReview contact metadata,
- any privacy, safety, legal, license, or redaction constraints.

Then ask the assistant to read `author-assistant-prompt.md` and prepare the final `submission-packet/`.

You remain responsible for checking the final paper, ARM Bundle, disclosure, citations, claims, redactions, and policy acknowledgements before submission.

## If You Are the AI Assistant

Your task is to produce:

```text
submission-packet/
  paper.pdf
  arm-bundle.zip
```

Use `arm-bundle-template/` as the starting structure. Replace all example content with paper-specific evidence. Do not fabricate missing traces, logs, citations, experiments, results, model versions, tool versions, or human approvals.

This track is for AI-led research. The declared primary AI contributor must be the primary research contributor and may be identified in the manuscript/PDF as the paper-level AI contributor or first author when accurate. OpenReview author fields must list human OpenReview profile holders only. Do not create or list an AI agent/system account as an OpenReview author. If the available evidence only shows an AI packaging assistant, proofreading assistant, or retrospective bundle-preparation assistant, mark the packet as not ready instead of trying to make it appear compliant.

In `autonomy_disclosure.yaml`, `primary_ai_contributor` only needs the AI system name and a short contribution summary. Detailed model versions, tools, and workflow details belong in the separate `agent_system` section.

The final `arm-bundle.zip` must contain this root structure:

```text
arm-bundle/
  manifest.yaml
  autonomy_disclosure.yaml
  README.md
  claims_index.yaml
  trace/
  execution/
  skill/
  knowledge_graph/
```

## Choose the Honest Reproducibility Level

Set the same level in OpenReview metadata, `manifest.yaml`, and `autonomy_disclosure.yaml`.

| Level | Meaning | What the `entry_point` should do |
| --- | --- | --- |
| `R0` | Re-executable from scratch | Rebuild results from raw or public inputs with documented environment setup, then write machine-readable checks. |
| `R1` | Re-executable with provided artifacts | Rerun the analysis from bundled data snapshots, cached model outputs, or provided intermediate artifacts, then write machine-readable checks. |
| `R2` | Partially re-executable | Rerun the feasible subset and explicitly mark expensive, private, unsafe, or unavailable steps as partial/redacted. |
| `R3` | Inspectable only | Run an inspection or consistency check; do not pretend to reproduce results. Prefer writing an `inspect_report.json` and point claims to inspectable evidence paths. |

For `R0`/`R1`, and for the executable part of `R2` when feasible, the entry point should produce:

```text
execution/generated_outputs/claim_checks.json
execution/generated_outputs/reproduce_report.json
```

Each headline claim in `claims_index.yaml` may point to these files with `verification.machine_check` so the validator and official review agent can verify claim-level pass/fail status.

For `R3`, use `verification.machine_check` only if the inspection entry point really writes a machine-checkable result. Otherwise map claims to submitted evidence, checksums, redaction statements, public references, or manual inspection instructions.

Do not include a pre-existing `execution/generated_outputs/` directory in the final zip. This directory is runtime output, not source evidence: it is created when the author, validator, or official review agent runs `entry_point`. Put source code, input data, cached model outputs, expected/reference outputs, and inspection artifacts that reviewers need to start from somewhere else, such as `execution/src/`, `execution/data/`, `execution/artifacts/`, or `execution/expected_outputs/`.

In other words: keep the materials needed to generate or inspect the results; exclude only the already-generated validator/review-agent output files so they cannot become stale or be mistaken for a fresh official run.

## Minimal Workflow

From the kit root:

```bash
mkdir -p work/submission-packet
cp /path/to/paper.pdf work/submission-packet/paper.pdf
cp -R arm-bundle-template work/arm-bundle
```

Edit `work/arm-bundle/` for the actual paper. Remove any template-only files, local hidden files, caches, and pre-generated `execution/generated_outputs/` before packaging. Do not remove real source artifacts, datasets, expected outputs, or bundled intermediate artifacts that are needed for the declared R-level:

```bash
rm -rf work/arm-bundle/execution/generated_outputs
find work/arm-bundle -name ".DS_Store" -delete
find work/arm-bundle -type d -name "__pycache__" -prune -exec rm -rf {} +
find work/arm-bundle -type d -name ".ipynb_checkpoints" -prune -exec rm -rf {} +
```

Then package and validate:

```bash
rm -f work/submission-packet/arm-bundle.zip
(cd work && zip -r submission-packet/arm-bundle.zip arm-bundle \
  -x "*/.DS_Store" "*/__pycache__/*" "*.pyc" "*/.ipynb_checkpoints/*" "*/execution/generated_outputs/*")
python3 validate_submission.py work/submission-packet --run-entry-point --output-dir work/validation-report
```

If the entry point is unsafe, expensive, private, or requires unavailable resources, omit `--run-entry-point` and explain the limitation in the ARM Bundle.

## Validator Status

- `pass` / exit code `0`: structurally ready for human review; not an acceptance decision.
- `warning` / exit code `1`: review and explain warnings before submission.
- `fail` / exit code `2`: fix failures before submission unless the PC explicitly allows an exception.

The validator will fail a packet that still looks like the unmodified template, contains `.git` metadata, declares only a packaging/proofreading AI assistant, or does not identify the declared AI system as the primary research contributor.

Use `--allow-template-placeholders` only to self-test the starter template. Do not use it for real submissions.

## Kit Contents

- `README.md`: this human quickstart and command reference.
- `author-assistant-prompt.md`: task prompt for Codex or another AI assistant.
- `arm-bundle-template/`: copy this to create the real ARM Bundle.
- `validate_submission.py`: single-file structural validator for `arm-bundle/`, `arm-bundle.zip`, or `submission-packet/`.

Detailed CFP and policy information is on the AI Paper Track website.
