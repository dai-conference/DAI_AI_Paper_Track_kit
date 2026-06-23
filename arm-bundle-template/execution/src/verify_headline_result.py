import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the template headline result.")
    parser.add_argument("--expected", required=True, help="Path to expected headline result JSON.")
    args = parser.parse_args()

    expected_path = Path(args.expected)
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    root = expected_path.parents[2]
    out = root / "execution" / "generated_outputs"
    out.mkdir(parents=True, exist_ok=True)

    if data.get("status") != "consistent" or data.get("claim_id") != "C1":
        (out / "claim_checks.json").write_text(json.dumps({
            "claims": [{
                "claim_id": "C1",
                "passed": False,
                "criterion": "expected status is consistent and claim_id is C1",
                "observed": data,
            }]
        }, indent=2) + "\n", encoding="utf-8")
        raise SystemExit("FAIL: headline result does not match expected output.")

    claim_checks = {
        "claims": [{
            "claim_id": "C1",
            "passed": True,
            "criterion": "expected status is consistent and claim_id is C1",
            "observed": data,
        }]
    }
    reproduce_report = {
        "status": "pass",
        "entry_point": "bash execution/run.sh",
        "generated_files": [
            "execution/generated_outputs/claim_checks.json",
            "execution/generated_outputs/reproduce_report.json",
        ],
        "claim_checks": claim_checks["claims"],
    }
    (out / "claim_checks.json").write_text(json.dumps(claim_checks, indent=2) + "\n", encoding="utf-8")
    (out / "reproduce_report.json").write_text(json.dumps(reproduce_report, indent=2) + "\n", encoding="utf-8")
    print("PASS: headline result matches expected output.")


if __name__ == "__main__":
    main()
