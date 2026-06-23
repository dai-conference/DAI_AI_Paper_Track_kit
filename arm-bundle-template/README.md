# ARM Bundle Verification Guide

Replace this file with a short reviewer guide for the actual paper. Keep the final version to 10 steps or fewer.

This starter template is a runnable `R2`-style dry-run example. It demonstrates the expected file layout, claim-to-evidence mapping, and generated machine checks. It is not a scientific example, and all example content must be replaced before submission.

## What This Bundle Contains

- `manifest.yaml`: bundle index and declared category, autonomy mode, reproducibility level, entry point, and redaction status.
- `autonomy_disclosure.yaml`: full AI/human role disclosure.
- `claims_index.yaml`: headline claims mapped to evidence and verification methods.
- `trace/`: observable workflow records.
- `execution/`: code or inspection artifacts and the declared entry point.
- `skill/`: prompts, agent configuration, and workflow configuration.
- `knowledge_graph/`: claims, citations, methods, datasets, artifacts, and relationships.

## Verification

From the ARM Bundle root, run:

```bash
bash execution/run.sh
```

Expected output for this template:

```text
PASS: headline result matches expected output.
```

The template writes:

```text
execution/generated_outputs/claim_checks.json
execution/generated_outputs/reproduce_report.json
```

For reproducible submissions, keep this convention when possible and reference the relevant JSON fields from `claims_index.yaml` using `verification.machine_check`.

Before packaging the final `arm-bundle.zip`, remove any pre-existing `execution/generated_outputs/`. This directory is runtime output created by local validation or official review-agent execution. Keep the source files and starting artifacts needed to rerun or inspect the work, but do not ship already-generated validator outputs that may be stale.

## Adapting the Template by R-Level

| Level | How to adapt this template |
| --- | --- |
| `R0` | Make `execution/run.sh` perform the complete clean rebuild from raw/public inputs. Pin environments and include data acquisition or generation instructions. |
| `R1` | Make `execution/run.sh` rerun from bundled snapshots, cached model outputs, or intermediate artifacts. Record provenance and checksums for those artifacts. |
| `R2` | Keep an executable subset. Clearly label unavailable steps as partial/redacted in `manifest.yaml`, `autonomy_disclosure.yaml`, and claim limitations. |
| `R3` | Replace reproduction logic with an inspection script. Do not claim a rerun; check file presence, checksums, redaction statements, and claim-evidence links. |

For `R3`, `verification.machine_check` is optional. Use it only when the inspection script writes a real machine-checkable output; otherwise provide evidence paths and manual inspection instructions.

## Redactions

This template has no redactions. If your real submission redacts material, record each redaction in `manifest.yaml`. If the list is longer than a few items, keep a paper-specific `redaction_statement.yaml` and set `redaction_statement: "redaction_statement.yaml"` in `manifest.yaml`.

Do not copy redaction examples unchanged. Each redaction must state the location, reason, affected claims, and alternative evidence where possible.
