#!/usr/bin/env python3
"""Validate a DAI 2026 AI Paper Track ARM Bundle or submission packet.

This is a single-file author-side validator. It can validate either:

- an ARM Bundle directory or .zip archive; or
- a submission-packet directory containing exactly paper.pdf and arm-bundle.zip.

It performs structural checks only. It does not judge scientific merit.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: python -m pip install pyyaml") from exc

VALID_CATEGORIES = {"ai_for_ai", "ai_for_x"}
VALID_AUTONOMY_MODES = {"fully_autonomous", "human_in_the_loop"}
VALID_REPRO_LEVELS = {"R0", "R1", "R2", "R3"}
CONTENT_STATUSES = {"present", "partial", "redacted"}
REQUIRED_DIRS = ["trace", "execution", "skill", "knowledge_graph"]
REQUIRED_TOP_FILES = ["manifest.yaml", "README.md", "autonomy_disclosure.yaml", "claims_index.yaml"]
REQUIRED_PACKET_FILES = {"paper.pdf", "arm-bundle.zip"}
REQUIRED_DISCLOSURE_STAGES = [
    "ideation",
    "literature_review",
    "hypothesis_generation",
    "experiment_design",
    "implementation",
    "data_collection",
    "analysis",
    "writing",
    "revision",
    "self_review_or_rebuttal",
]
VALID_ROLE_MODES = {
    "ai_performed_independently",
    "ai_proposed_human_selected",
    "human_directed_ai_executed",
    "human_performed_ai_assisted",
    "not_applicable",
}
TEXT_SUFFIXES = {".txt", ".md", ".yaml", ".yml", ".json", ".jsonl", ".py", ".sh", ".toml", ".cfg", ".ini"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
]
TEMPLATE_PLACEHOLDER_PATTERNS = [
    re.compile(r"Example AI Paper Title"),
    re.compile(r"Example Research Agent"),
    re.compile(r"Anonymous Human Author"),
    re.compile(r"Replace with"),
    re.compile(r"template headline result", re.I),
    re.compile(r"template verification", re.I),
    re.compile(r"verify_headline_result\.py"),
    re.compile(r"headline_result\.json"),
    re.compile(r"citation:openreview"),
]
SUPPORT_ONLY_AI_ROLE_MARKERS = {
    "packaging_assistant",
    "proofreading_assistant",
    "editing_assistant",
    "formatting_assistant",
    "submission_preparation_assistant",
    "bundle_preparation_assistant",
    "retrospective_packaging_assistant",
}
NOT_AI_FIRST_SCOPE_MARKERS = [
    "not ai-first",
    "not ai first",
    "not evidence of ai-first",
    "not evidence that the original",
    "not the original research agent",
    "only prepared the bundle",
    "retrospective bundle preparation",
    "retrospective packaging simulation",
    "packaging simulation only",
    "support-only assistant",
]


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    path: str | None = None


@dataclass
class Report:
    target_path: str
    target_type: str
    status: str = "pass"
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def add(self, severity: str, code: str, message: str, path: str | None = None) -> None:
        self.findings.append(Finding(severity, code, message, path))

    def finalize(self) -> None:
        severities = {f.severity for f in self.findings}
        if "fail" in severities:
            self.status = "fail"
        elif "warning" in severities:
            self.status = "warning"
        else:
            self.status = "pass"
        self.summary["counts"] = {
            "fail": sum(1 for f in self.findings if f.severity == "fail"),
            "warning": sum(1 for f in self.findings if f.severity == "warning"),
            "info": sum(1 for f in self.findings if f.severity == "info"),
        }

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "target_path": self.target_path,
            "target_type": self.target_type,
            "status": self.status,
            "summary": self.summary,
            "findings": [f.__dict__ for f in self.findings],
        }


def load_yaml(path: Path, report: Report) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report.add("fail", "yaml_parse_error", f"Could not parse YAML: {exc}", str(path))
        return None


def load_json(path: Path, report: Report) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report.add("fail", "json_parse_error", f"Could not parse JSON: {exc}", str(path))
        return None


def unpack_bundle(bundle: Path, temp_dir: Path) -> Path:
    if bundle.is_dir():
        return bundle.resolve()
    if bundle.suffix != ".zip":
        raise ValueError("ARM Bundle must be a directory or .zip archive")
    with zipfile.ZipFile(bundle) as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe zip path: {member.filename}")
            target = (temp_dir / member.filename).resolve()
            try:
                target.relative_to(temp_dir.resolve())
            except ValueError:
                raise ValueError(f"Unsafe zip path: {member.filename}")
        zf.extractall(temp_dir)
    children = [p for p in temp_dir.iterdir() if not p.name.startswith("__MACOSX")]
    if len(children) == 1 and children[0].is_dir():
        return children[0].resolve()
    return temp_dir.resolve()


def get_nested(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def rel_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def check_bundle_hygiene(root: Path, report: Report) -> None:
    generated = root / "execution" / "generated_outputs"
    if generated.exists():
        report.add(
            "warning",
            "preexisting_generated_outputs",
            "Remove execution/generated_outputs before packaging; validator and review agent regenerate it",
            "execution/generated_outputs",
        )

    for path in root.rglob("*"):
        rel = rel_to_root(path, root)
        parts = set(path.parts)
        name = path.name
        if name == ".DS_Store" or "__MACOSX" in parts:
            report.add("warning", "local_metadata_file", "Remove local OS metadata files before packaging", rel)
        elif name == "__pycache__" or "__pycache__" in parts or path.suffix == ".pyc":
            report.add("warning", "python_cache_file", "Remove Python cache files before packaging", rel)
        elif ".git" in parts or name == ".git":
            report.add("fail", "git_metadata_in_bundle", "Do not include .git metadata in the ARM Bundle", rel)
        elif ".ipynb_checkpoints" in parts or name == ".ipynb_checkpoints":
            report.add("warning", "notebook_checkpoint_in_bundle", "Remove notebook checkpoint folders before packaging", rel)
        elif ".example." in name:
            report.add("warning", "example_file_in_bundle", "Do not include unchanged example files in the final ARM Bundle", rel)


def check_template_placeholders(root: Path, report: Report, allow_template_placeholders: bool) -> None:
    if allow_template_placeholders:
        return
    files = [
        root / "manifest.yaml",
        root / "autonomy_disclosure.yaml",
        root / "claims_index.yaml",
        root / "README.md",
        root / "knowledge_graph" / "graph.json",
        root / "skill" / "agent_config.yaml",
        root / "skill" / "prompts.md",
        root / "trace" / "trace.jsonl",
        root / "execution" / "src" / "verify_headline_result.py",
        root / "execution" / "expected_outputs" / "headline_result.json",
    ]
    for path in files:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in TEMPLATE_PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                report.add(
                    "fail",
                    "template_placeholder_not_replaced",
                    f"Template placeholder or example content remains: {pattern.pattern}",
                    rel_to_root(path, root),
                )
                break


def entry_point_target(entry_point: str) -> str | None:
    try:
        parts = shlex.split(entry_point)
    except ValueError:
        parts = entry_point.split()
    if not parts:
        return None
    interpreters = {"bash", "sh", "python", "python3", "Rscript", "node"}
    if parts[0] in interpreters and len(parts) >= 2:
        return parts[1]
    if "/" in parts[0] or parts[0].startswith("."):
        return parts[0]
    return None


def check_structure(root: Path, report: Report) -> None:
    for name in REQUIRED_TOP_FILES:
        if not (root / name).is_file():
            report.add("fail", "missing_required_file", f"Missing required file: {name}", name)
    for name in REQUIRED_DIRS:
        if not (root / name).is_dir():
            report.add("fail", "missing_required_dir", f"Missing required directory: {name}/", name)


def check_manifest(root: Path, report: Report) -> dict[str, Any] | None:
    path = root / "manifest.yaml"
    if not path.exists():
        return None
    manifest = load_yaml(path, report)
    if not isinstance(manifest, dict):
        report.add("fail", "manifest_not_object", "manifest.yaml must contain a YAML object", "manifest.yaml")
        return None

    required = [
        "title", "category", "autonomy_mode", "agent_system.name", "agent_system.base_models",
        "agent_system.tools", "contents.trace", "contents.execution", "contents.skill",
        "contents.knowledge_graph", "reproducibility_level", "entry_point", "claims_index", "redactions",
    ]
    for field_path in required:
        if get_nested(manifest, field_path) is None:
            report.add("fail", "missing_manifest_field", f"Missing manifest field: {field_path}", "manifest.yaml")

    if manifest.get("category") not in VALID_CATEGORIES:
        report.add("fail", "invalid_category", f"Invalid category: {manifest.get('category')}", "manifest.yaml")
    if manifest.get("autonomy_mode") not in VALID_AUTONOMY_MODES:
        report.add("fail", "invalid_autonomy_mode", f"Invalid autonomy_mode: {manifest.get('autonomy_mode')}", "manifest.yaml")
    if manifest.get("reproducibility_level") not in VALID_REPRO_LEVELS:
        report.add("fail", "invalid_reproducibility_level", f"Invalid reproducibility_level: {manifest.get('reproducibility_level')}", "manifest.yaml")

    agent_system = manifest.get("agent_system")
    if isinstance(agent_system, dict):
        for key in ("base_models", "tools"):
            value = agent_system.get(key)
            if not isinstance(value, list) or not value:
                report.add("fail", "invalid_agent_system_list", f"agent_system.{key} must be a non-empty list", "manifest.yaml")

    contents = manifest.get("contents", {})
    if isinstance(contents, dict):
        for key in REQUIRED_DIRS:
            value = contents.get(key)
            if value not in CONTENT_STATUSES:
                report.add("fail", "invalid_content_status", f"Invalid contents.{key}: {value}", "manifest.yaml")
            if value in {"partial", "redacted"} and not manifest.get("redactions"):
                report.add("warning", "content_status_needs_redaction_note", f"contents.{key} is {value}, but redactions is empty", "manifest.yaml")

    entry_point = manifest.get("entry_point")
    if isinstance(entry_point, str):
        target = entry_point_target(entry_point)
        if target and not (root / target).exists():
            report.add("fail", "missing_entry_point", f"Entry point target not found: {target}", entry_point)

    claims_index = manifest.get("claims_index")
    if isinstance(claims_index, str) and not (root / claims_index).exists():
        report.add("fail", "missing_claims_index", f"Claims index not found: {claims_index}", claims_index)

    redactions = manifest.get("redactions")
    if redactions is not None and not isinstance(redactions, list):
        report.add("fail", "invalid_redactions", "manifest.redactions must be a list", "manifest.yaml")

    report.summary["manifest"] = {
        "title": manifest.get("title"),
        "category": manifest.get("category"),
        "autonomy_mode": manifest.get("autonomy_mode"),
        "reproducibility_level": manifest.get("reproducibility_level"),
        "entry_point": manifest.get("entry_point"),
        "claims_index": manifest.get("claims_index"),
    }
    return manifest


def check_autonomy_disclosure(root: Path, manifest: dict[str, Any] | None, report: Report) -> None:
    path = root / "autonomy_disclosure.yaml"
    if not path.exists():
        return
    data = load_yaml(path, report)
    if not isinstance(data, dict):
        report.add("fail", "disclosure_not_object", "autonomy_disclosure.yaml must contain a YAML object", "autonomy_disclosure.yaml")
        return

    required_top = [
        "submission_title", "research_domain", "autonomy_mode", "reproducibility_level",
        "primary_ai_contributor", "agent_system", "human_contributors",
        "stages", "validation_and_integrity",
    ]
    for key in required_top:
        if key not in data:
            report.add("fail", "missing_disclosure_field", f"Missing autonomy_disclosure field: {key}", "autonomy_disclosure.yaml")

    if manifest:
        pairs = [("research_domain", "category"), ("autonomy_mode", "autonomy_mode"), ("reproducibility_level", "reproducibility_level")]
        for disclosure_key, manifest_key in pairs:
            if data.get(disclosure_key) and data.get(disclosure_key) != manifest.get(manifest_key):
                report.add("fail", "disclosure_manifest_mismatch", f"{disclosure_key} does not match manifest.{manifest_key}", "autonomy_disclosure.yaml")

    primary = data.get("primary_ai_contributor")
    if not isinstance(primary, dict):
        report.add("fail", "primary_ai_contributor_not_object", "primary_ai_contributor must be an object", "autonomy_disclosure.yaml")
    else:
        name = str(primary.get("name") or "").strip()
        contribution_summary = str(primary.get("contribution_summary") or "").strip()
        if not name:
            report.add("fail", "primary_ai_contributor_missing_name", "Primary AI contributor name is required", "autonomy_disclosure.yaml")
        if not contribution_summary:
            report.add(
                "fail",
                "primary_ai_contribution_summary_missing",
                "primary_ai_contributor.contribution_summary must briefly state the AI system's primary research contribution",
                "autonomy_disclosure.yaml",
            )
        primary_text = json.dumps(primary, ensure_ascii=False).lower()
        support_markers = sorted(marker for marker in SUPPORT_ONLY_AI_ROLE_MARKERS if marker in primary_text)
        if support_markers:
            report.add(
                "fail",
                "support_agent_used_as_primary_ai_contributor",
                f"Support role marker(s) {', '.join(support_markers)} cannot be used as the primary AI contributor for a ready packet",
                "autonomy_disclosure.yaml",
            )

    disclosure_agent = data.get("agent_system")
    if not isinstance(disclosure_agent, dict):
        report.add("fail", "disclosure_agent_system_not_object", "agent_system must be an object", "autonomy_disclosure.yaml")
    else:
        for key in ("name", "version"):
            if not str(disclosure_agent.get(key) or "").strip():
                report.add("fail", "disclosure_agent_system_missing_field", f"agent_system.{key} is required", "autonomy_disclosure.yaml")
        for key in ("base_models", "tools"):
            value = disclosure_agent.get(key)
            if not isinstance(value, list) or not value:
                report.add("fail", "disclosure_agent_system_invalid_list", f"agent_system.{key} must be a non-empty list", "autonomy_disclosure.yaml")

    humans = data.get("human_contributors")
    if not isinstance(humans, list) or not humans:
        report.add("fail", "human_contributors_invalid", "human_contributors must be a non-empty list", "autonomy_disclosure.yaml")
    else:
        for idx, human in enumerate(humans, start=1):
            hpath = f"autonomy_disclosure.yaml#human_contributors[{idx}]"
            if not isinstance(human, dict):
                report.add("fail", "human_contributor_not_object", "Each human contributor must be an object", hpath)
                continue
            for key in ("role", "contribution_summary"):
                if not str(human.get(key) or "").strip():
                    report.add("warning", "human_contributor_missing_detail", f"Human contributor missing {key}", hpath)

    redaction_summary = data.get("redaction_summary")
    if isinstance(redaction_summary, dict) and manifest:
        redactions_present = redaction_summary.get("redactions_present")
        manifest_has_redactions = bool(manifest.get("redactions"))
        if redactions_present is False and manifest_has_redactions:
            report.add(
                "fail",
                "redaction_summary_mismatch",
                "redaction_summary.redactions_present is false but manifest.redactions is not empty",
                "autonomy_disclosure.yaml",
            )

    disclosure_text = path.read_text(encoding="utf-8", errors="ignore").lower()
    for marker in NOT_AI_FIRST_SCOPE_MARKERS:
        if marker in disclosure_text:
            report.add(
                "fail",
                "disclosure_scope_not_ai_first_research",
                f"Disclosure says the packet is not evidence of AI-first research: {marker}",
                "autonomy_disclosure.yaml",
            )
            break

    stages = data.get("stages")
    if not isinstance(stages, dict):
        report.add("fail", "disclosure_missing_stages", "Disclosure must contain stages object", "autonomy_disclosure.yaml")
    else:
        for stage in REQUIRED_DISCLOSURE_STAGES:
            item = stages.get(stage)
            if not isinstance(item, dict):
                report.add("fail", "disclosure_missing_stage", f"Missing disclosure stage: {stage}", "autonomy_disclosure.yaml")
                continue
            role_mode = item.get("role_mode")
            if role_mode not in VALID_ROLE_MODES:
                report.add("fail", "invalid_role_mode", f"Invalid role_mode for {stage}: {role_mode}", "autonomy_disclosure.yaml")
            if role_mode != "not_applicable" and not (item.get("ai_actions") or item.get("human_actions")):
                report.add("warning", "stage_missing_actions", f"Stage {stage} has no ai_actions or human_actions", "autonomy_disclosure.yaml")
        report.summary["autonomy_disclosure"] = {"stage_count": len(stages), "stages_present": sorted(stages.keys())}


def check_claims_index(root: Path, manifest: dict[str, Any] | None, report: Report) -> dict[str, Any] | None:
    claims_path = root / ((manifest or {}).get("claims_index") or "claims_index.yaml")
    if not claims_path.exists():
        return None
    data = load_yaml(claims_path, report)
    if not isinstance(data, dict):
        report.add("fail", "claims_index_not_object", "claims_index must contain a YAML object", str(claims_path.relative_to(root)))
        return None
    claims = data.get("claims")
    if not isinstance(claims, list) or not claims:
        report.add("fail", "claims_missing", "claims_index must contain a non-empty claims list", str(claims_path.relative_to(root)))
        return data
    ids: set[str] = set()
    for idx, claim in enumerate(claims, start=1):
        cpath = f"{claims_path.relative_to(root)}#claims[{idx}]"
        if not isinstance(claim, dict):
            report.add("fail", "claim_not_object", "Each claim must be an object", cpath)
            continue
        claim_id = claim.get("claim_id")
        if not claim_id:
            report.add("fail", "claim_missing_id", "Claim is missing claim_id", cpath)
        elif claim_id in ids:
            report.add("fail", "duplicate_claim_id", f"Duplicate claim_id: {claim_id}", cpath)
        else:
            ids.add(claim_id)
        if not claim.get("claim_text"):
            report.add("fail", "claim_missing_text", "Claim is missing claim_text", cpath)
        if not claim.get("support"):
            report.add("warning", "claim_missing_support", "Claim has no support block", cpath)
        if not claim.get("verification"):
            report.add("warning", "claim_missing_verification", "Claim has no verification block", cpath)
    report.summary["claims"] = {"count": len(claims), "claim_ids": sorted(ids)}
    return data


def has_citation_identifier(node: dict[str, Any]) -> bool:
    for key in ("doi", "arxiv_id", "arxiv", "url"):
        if isinstance(node.get(key), str) and node.get(key).strip():
            return True
    identifiers = node.get("identifiers")
    if isinstance(identifiers, dict):
        return any(str(identifiers.get(k, "")).strip() for k in ("doi", "arxiv_id", "arxiv", "url"))
    return False


def check_knowledge_graph(root: Path, report: Report) -> None:
    kg_dir = root / "knowledge_graph"
    if not kg_dir.is_dir():
        return
    candidates = [kg_dir / "graph.json", kg_dir / "graph.yaml", kg_dir / "graph.yml"]
    graph_path = next((p for p in candidates if p.exists()), None)
    if graph_path is None:
        report.add("fail", "missing_knowledge_graph_file", "No graph.json, graph.yaml, or graph.yml found", "knowledge_graph")
        return
    graph = load_json(graph_path, report) if graph_path.suffix == ".json" else load_yaml(graph_path, report)
    if not isinstance(graph, dict):
        report.add("fail", "knowledge_graph_not_object", "Knowledge graph must contain an object", str(graph_path.relative_to(root)))
        return
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not nodes:
        report.add("fail", "knowledge_graph_missing_nodes", "Knowledge graph must contain a non-empty nodes list", str(graph_path.relative_to(root)))
        return
    if not isinstance(edges, list):
        report.add("fail", "knowledge_graph_missing_edges", "Knowledge graph must contain an edges list", str(graph_path.relative_to(root)))
    citation_nodes = [n for n in nodes if isinstance(n, dict) and n.get("type") == "citation"]
    missing = [str(n.get("id", "<unknown>")) for n in citation_nodes if not has_citation_identifier(n)]
    if missing:
        report.add("fail", "citation_missing_identifier", "Citation nodes missing DOI/arXiv/URL: " + ", ".join(missing), str(graph_path.relative_to(root)))
    report.summary["knowledge_graph"] = {"node_count": len(nodes), "citation_count": len(citation_nodes), "citation_missing_identifier_count": len(missing)}


def check_redactions(root: Path, manifest: dict[str, Any] | None, report: Report) -> None:
    if not manifest:
        return
    redactions = manifest.get("redactions", [])
    if isinstance(redactions, list):
        for idx, item in enumerate(redactions, start=1):
            if isinstance(item, str):
                if not item.strip():
                    report.add("warning", "empty_redaction_reason", "Empty redaction reason", f"manifest.yaml#redactions[{idx}]")
            elif isinstance(item, dict):
                for field in ("item_id", "location", "reason"):
                    if not item.get(field):
                        report.add("warning", "redaction_item_incomplete", f"Redaction item missing {field}", f"manifest.yaml#redactions[{idx}]")
            else:
                report.add("warning", "redaction_unknown_format", "Redaction item should be string or object", f"manifest.yaml#redactions[{idx}]")
    redaction_statement = manifest.get("redaction_statement")
    if isinstance(redaction_statement, str) and redaction_statement.strip() and not (root / redaction_statement).exists():
        report.add("fail", "missing_redaction_statement", f"redaction_statement not found: {redaction_statement}", "manifest.yaml")
    report.summary["redactions"] = {"count": len(redactions) if isinstance(redactions, list) else 0, "redaction_statement": redaction_statement}


def scan_for_secrets(root: Path, report: Report) -> None:
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                report.add("warning", "possible_secret", "Possible API key, token, password, or secret pattern found", rel)
                count += 1
                break
    report.summary["secret_scan"] = {"possible_secret_count": count}


def run_entry_point(root: Path, manifest: dict[str, Any] | None, timeout: int, report: Report) -> None:
    if not manifest or not manifest.get("entry_point"):
        return
    cmd = str(manifest["entry_point"])
    try:
        result = subprocess.run(cmd, cwd=root, shell=True, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        report.add("fail", "entry_point_timeout", f"Entry point timed out after {timeout}s", cmd)
        report.summary["entry_point_run"] = {"status": "timeout", "command": cmd}
        return
    except Exception as exc:
        report.add("fail", "entry_point_error", f"Could not run entry point: {exc}", cmd)
        report.summary["entry_point_run"] = {"status": "error", "command": cmd, "error": str(exc)}
        return
    if result.returncode == 0:
        report.add("info", "entry_point_passed", "Entry point completed successfully", cmd)
        status = "pass"
    else:
        report.add("fail", "entry_point_failed", f"Entry point exited with code {result.returncode}", cmd)
        status = "fail"
    report.summary["entry_point_run"] = {
        "status": status,
        "command": cmd,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def json_pointer_get(data: Any, pointer: str) -> Any:
    if pointer == "":
        return data
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    current = data
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(part)
    return current


def as_machine_check_list(machine_check: Any) -> list[dict[str, Any]]:
    if isinstance(machine_check, dict):
        return [machine_check]
    if isinstance(machine_check, list):
        return [item for item in machine_check if isinstance(item, dict)]
    return []


def extract_claim_check_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        claims = data.get("claims")
        if isinstance(claims, list):
            return [item for item in claims if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def summarize_generated_outputs(root: Path, manifest: dict[str, Any] | None, claims_index: dict[str, Any] | None, report: Report) -> None:
    generated_dir = root / "execution" / "generated_outputs"
    summary: dict[str, Any] = {"present": generated_dir.is_dir(), "files": []}
    indexed_claim_ids = [
        str(claim.get("claim_id"))
        for claim in (claims_index or {}).get("claims", []) or []
        if isinstance(claim, dict) and claim.get("claim_id")
    ]
    if generated_dir.is_dir():
        for path in sorted(p for p in generated_dir.rglob("*") if p.is_file()):
            summary["files"].append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size})

    reproduce_path = generated_dir / "reproduce_report.json"
    if reproduce_path.exists():
        reproduce_report = load_json(reproduce_path, report)
        if isinstance(reproduce_report, dict):
            status = reproduce_report.get("status")
            summary["reproduce_report"] = {
                "path": str(reproduce_path.relative_to(root)),
                "status": status,
                "generated_files": reproduce_report.get("generated_files", []),
            }
            if status and str(status).lower() not in {"pass", "passed", "success", "ok"}:
                report.add("fail", "reproduce_report_failed", f"reproduce_report.json status is {status}", str(reproduce_path.relative_to(root)))

    inspect_path = generated_dir / "inspect_report.json"
    if inspect_path.exists():
        inspect_report = load_json(inspect_path, report)
        if isinstance(inspect_report, dict):
            status = inspect_report.get("status")
            summary["inspect_report"] = {
                "path": str(inspect_path.relative_to(root)),
                "status": status,
                "checks": inspect_report.get("checks", []),
            }
            status_lower = str(status or "").lower()
            if status_lower in {"fail", "failed", "error"}:
                report.add("fail", "inspect_report_failed", f"inspect_report.json status is {status}", str(inspect_path.relative_to(root)))
            elif status_lower in {"warning", "warn"}:
                report.add("warning", "inspect_report_warning", f"inspect_report.json status is {status}", str(inspect_path.relative_to(root)))

    claim_checks_path = generated_dir / "claim_checks.json"
    generated_claim_items: list[dict[str, Any]] = []
    if claim_checks_path.exists():
        claim_checks_data = load_json(claim_checks_path, report)
        generated_claim_items = extract_claim_check_items(claim_checks_data)
        failed = [str(item.get("claim_id", "<unknown>")) for item in generated_claim_items if item.get("passed") is False]
        summary["claim_checks"] = {
            "path": str(claim_checks_path.relative_to(root)),
            "claim_count": len(generated_claim_items),
            "passed_count": sum(1 for item in generated_claim_items if item.get("passed") is True),
            "failed_ids": failed,
            "items": generated_claim_items,
        }
        if failed:
            report.add("fail", "generated_claim_check_failed", "Generated claim checks failed: " + ", ".join(failed), str(claim_checks_path.relative_to(root)))
        generated_ids = [str(item.get("claim_id")) for item in generated_claim_items if item.get("claim_id")]
        missing_ids = sorted(set(indexed_claim_ids) - set(generated_ids))
        extra_ids = sorted(set(generated_ids) - set(indexed_claim_ids))
        if missing_ids:
            report.add(
                "fail",
                "generated_claim_checks_missing_indexed_claims",
                "Generated claim checks missing indexed claim IDs: " + ", ".join(missing_ids),
                str(claim_checks_path.relative_to(root)),
            )
        if extra_ids:
            report.add(
                "warning",
                "generated_claim_checks_extra_claims",
                "Generated claim checks contain IDs not listed in claims_index.yaml: " + ", ".join(extra_ids),
                str(claim_checks_path.relative_to(root)),
            )

    machine_results: list[dict[str, Any]] = []
    for claim in (claims_index or {}).get("claims", []) or []:
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        verification = claim.get("verification")
        if not isinstance(verification, dict):
            continue
        for machine_check in as_machine_check_list(verification.get("machine_check")):
            rel_path = machine_check.get("path")
            pointer = machine_check.get("json_pointer")
            expected = machine_check.get("expected")
            result: dict[str, Any] = {"claim_id": claim_id, "path": rel_path, "json_pointer": pointer, "expected": expected}
            if not rel_path or pointer is None:
                result["status"] = "invalid"
                report.add("warning", "invalid_machine_check", f"Machine check for {claim_id} must include path and json_pointer", "claims_index.yaml")
                machine_results.append(result)
                continue
            target = root / str(rel_path)
            if not target.exists():
                result["status"] = "missing_output"
                report.add("fail", "machine_check_output_missing", f"Machine-check output missing for {claim_id}: {rel_path}", str(rel_path))
                machine_results.append(result)
                continue
            data = load_json(target, report)
            try:
                actual = json_pointer_get(data, str(pointer))
            except Exception as exc:
                result["status"] = "pointer_error"
                result["error"] = str(exc)
                report.add("fail", "machine_check_pointer_error", f"Could not read {pointer} for {claim_id}: {exc}", str(rel_path))
                machine_results.append(result)
                continue
            result["actual"] = actual
            if actual == expected:
                result["status"] = "pass"
            else:
                result["status"] = "fail"
                report.add("fail", "machine_check_failed", f"Machine check failed for {claim_id}: expected {expected!r}, got {actual!r}", str(rel_path))
            machine_results.append(result)
    if machine_results:
        summary["machine_checks"] = {
            "count": len(machine_results),
            "passed_count": sum(1 for item in machine_results if item.get("status") == "pass"),
            "items": machine_results,
        }

    repro = (manifest or {}).get("reproducibility_level")
    entry_status = (report.summary.get("entry_point_run") or {}).get("status")
    if entry_status == "pass" and repro in {"R0", "R1", "R2"}:
        if not summary["present"]:
            severity = "fail" if repro in {"R0", "R1"} else "warning"
            report.add(severity, "missing_generated_outputs", f"{repro} entry point passed but execution/generated_outputs/ was not produced", "execution/generated_outputs")
        if not machine_results and not generated_claim_items:
            severity = "fail" if repro in {"R0", "R1"} else "warning"
            report.add(severity, "missing_machine_readable_claim_checks", f"{repro} should include machine-readable claim checks when feasible", "claims_index.yaml")
        if generated_claim_items and indexed_claim_ids and not machine_results:
            severity = "fail" if repro in {"R0", "R1"} else "warning"
            report.add(
                severity,
                "claims_missing_declared_machine_checks",
                f"{repro} generated claim checks should be referenced from claims_index.yaml via verification.machine_check",
                "claims_index.yaml",
            )

    if entry_status == "pass" and repro == "R3":
        if not (generated_dir / "inspect_report.json").exists() and not generated_claim_items and not machine_results:
            report.add(
                "warning",
                "missing_r3_inspection_output",
                "R3 entry point passed but did not produce inspect_report.json or machine-readable checks",
                "execution/generated_outputs",
            )

    report.summary["generated_outputs"] = summary


def validate_arm_bundle(path: Path, run: bool, timeout: int, allow_template_placeholders: bool = False) -> Report:
    report = Report(target_path=str(path), target_type="arm_bundle")
    with tempfile.TemporaryDirectory(prefix="arm_bundle_validate_") as tmp:
        try:
            root = unpack_bundle(path, Path(tmp))
        except Exception as exc:
            report.add("fail", "bundle_unpack_error", str(exc), str(path))
            report.finalize()
            return report
        check_bundle_hygiene(root, report)
        check_template_placeholders(root, report, allow_template_placeholders)
        check_structure(root, report)
        manifest = check_manifest(root, report)
        check_autonomy_disclosure(root, manifest, report)
        claims_index = check_claims_index(root, manifest, report)
        check_knowledge_graph(root, report)
        check_redactions(root, manifest, report)
        scan_for_secrets(root, report)
        if run:
            run_entry_point(root, manifest, timeout, report)
            summarize_generated_outputs(root, manifest, claims_index, report)
    report.finalize()
    return report


def validate_packet(packet: Path, run: bool, timeout: int, allow_template_placeholders: bool = False) -> Report:
    report = Report(target_path=str(packet), target_type="submission_packet")
    if not packet.is_dir():
        report.add("fail", "packet_not_directory", "Submission packet must be a directory", str(packet))
        report.finalize()
        return report
    for name in sorted(REQUIRED_PACKET_FILES):
        item = packet / name
        if not item.is_file():
            report.add("fail", "missing_packet_file", f"Missing required packet file: {name}", name)
    for child in sorted(packet.iterdir(), key=lambda p: p.name):
        if child.name in REQUIRED_PACKET_FILES:
            continue
        if child.name.startswith("."):
            report.add("warning", "unexpected_hidden_packet_item", "Remove hidden local files before upload", child.name)
        else:
            report.add("fail", "unexpected_packet_item", "Submission packet should contain only paper.pdf and arm-bundle.zip", child.name)
    pdf = packet / "paper.pdf"
    if pdf.is_file() and pdf.stat().st_size == 0:
        report.add("fail", "empty_pdf", "paper.pdf is empty", "paper.pdf")
    bundle = packet / "arm-bundle.zip"
    if bundle.is_file() and not zipfile.is_zipfile(bundle):
        report.add("fail", "invalid_arm_bundle_zip", "arm-bundle.zip is not a valid zip archive", "arm-bundle.zip")
    if bundle.exists():
        arm_report = validate_arm_bundle(bundle, run=run, timeout=timeout, allow_template_placeholders=allow_template_placeholders)
        report.summary["arm_bundle"] = arm_report.to_jsonable()
        for finding in arm_report.findings:
            report.findings.append(Finding(finding.severity, "arm_" + finding.code, finding.message, finding.path))
    report.summary["expected_upload_files"] = sorted(REQUIRED_PACKET_FILES)
    report.finalize()
    return report


def render_markdown(report: Report) -> str:
    lines = [
        "# DAI 2026 AI Paper Track Validation Report",
        "",
        f"- Target: `{report.target_path}`",
        f"- Target type: `{report.target_type}`",
        f"- Overall status: `{report.status}`",
    ]
    counts = report.summary.get("counts", {})
    if counts:
        lines.append(f"- Findings: {counts.get('fail', 0)} fail, {counts.get('warning', 0)} warning, {counts.get('info', 0)} info")
    manifest = report.summary.get("manifest") or (report.summary.get("arm_bundle", {}).get("summary", {}).get("manifest") if isinstance(report.summary.get("arm_bundle"), dict) else None)
    if manifest:
        lines.extend([
            "",
            "## Submission Summary",
            "",
            f"- Title: {manifest.get('title')}",
            f"- Category: `{manifest.get('category')}`",
            f"- Autonomy mode: `{manifest.get('autonomy_mode')}`",
            f"- Reproducibility level: `{manifest.get('reproducibility_level')}`",
            f"- Entry point: `{manifest.get('entry_point')}`",
        ])
    lines.extend(["", "## Findings", ""])
    if not report.findings:
        lines.append("No findings.")
    else:
        for finding in report.findings:
            path = f" (`{finding.path}`)" if finding.path else ""
            lines.append(f"- `{finding.severity}` `{finding.code}`{path}: {finding.message}")
    entry = report.summary.get("entry_point_run") or (report.summary.get("arm_bundle", {}).get("summary", {}).get("entry_point_run") if isinstance(report.summary.get("arm_bundle"), dict) else None)
    if entry:
        lines.extend(["", "## Entry Point Run", "", f"- Status: `{entry.get('status')}`", f"- Command: `{entry.get('command')}`"])
        if entry.get("stdout_tail"):
            lines.extend(["", "Stdout tail:", "", "```text", str(entry["stdout_tail"]).strip(), "```"])
        if entry.get("stderr_tail"):
            lines.extend(["", "Stderr tail:", "", "```text", str(entry["stderr_tail"]).strip(), "```"])
    generated = report.summary.get("generated_outputs") or (report.summary.get("arm_bundle", {}).get("summary", {}).get("generated_outputs") if isinstance(report.summary.get("arm_bundle"), dict) else None)
    if generated:
        claim_checks = generated.get("claim_checks") or {}
        machine_checks = generated.get("machine_checks") or {}
        lines.extend([
            "",
            "## Generated Output Checks",
            "",
            f"- `execution/generated_outputs/` present: `{generated.get('present')}`",
            f"- Generated files: `{len(generated.get('files') or [])}`",
        ])
        if claim_checks:
            lines.append(f"- Claim checks: `{claim_checks.get('passed_count', 0)}/{claim_checks.get('claim_count', 0)}` passed")
        if machine_checks:
            lines.append(f"- Declared machine checks: `{machine_checks.get('passed_count', 0)}/{machine_checks.get('count', 0)}` passed")
        inspect_report = generated.get("inspect_report") or {}
        if inspect_report:
            lines.append(f"- Inspection report status: `{inspect_report.get('status')}`")
    lines.extend(["", "## Meaning", ""])
    if report.status == "pass":
        lines.append("The packet is structurally ready for human review. This is not an acceptance decision.")
    elif report.status == "warning":
        lines.append("Review all warnings before submitting. The OpenReview authors should decide whether clarification is needed.")
    else:
        lines.append("Fix failures before submitting, or prepare a clear explanation if the PC explicitly allows an exception.")
    return "\n".join(lines) + "\n"


def detect_target_type(path: Path) -> str:
    if path.is_dir() and ((path / "paper.pdf").exists() or (path / "arm-bundle.zip").exists()):
        return "packet"
    return "bundle"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a DAI 2026 AI Paper Track ARM Bundle or submission packet.")
    parser.add_argument("target", help="Path to arm-bundle directory, arm-bundle.zip, or submission-packet directory")
    parser.add_argument("--packet", action="store_true", help="Force target to be treated as a submission-packet directory")
    parser.add_argument("--bundle", action="store_true", help="Force target to be treated as an ARM Bundle directory or zip")
    parser.add_argument("--run-entry-point", action="store_true", help="Run the ARM Bundle entry point. Use only for trusted local bundles.")
    parser.add_argument("--timeout", type=int, default=300, help="Entry point timeout in seconds")
    parser.add_argument("--output-dir", help="Directory for validation_report.json and validation_report.md")
    parser.add_argument("--allow-template-placeholders", action="store_true", help="Allow the unmodified Author Kit template to self-test. Do not use for final submissions.")
    args = parser.parse_args()

    target = Path(args.target)
    if args.packet and args.bundle:
        raise SystemExit("Use only one of --packet or --bundle")
    target_type = "packet" if args.packet else "bundle" if args.bundle else detect_target_type(target)
    report = (
        validate_packet(target, args.run_entry_point, args.timeout, allow_template_placeholders=args.allow_template_placeholders)
        if target_type == "packet"
        else validate_arm_bundle(target, args.run_entry_point, args.timeout, allow_template_placeholders=args.allow_template_placeholders)
    )

    report_json = json.dumps(report.to_jsonable(), indent=2, ensure_ascii=False) + "\n"
    report_md = render_markdown(report)
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "validation_report.json").write_text(report_json, encoding="utf-8")
        (out / "validation_report.md").write_text(report_md, encoding="utf-8")
    else:
        print(report_md)
    if report.status == "fail":
        raise SystemExit(2)
    if report.status == "warning":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
