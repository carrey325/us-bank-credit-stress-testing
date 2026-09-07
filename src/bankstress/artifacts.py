from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


R1_DEFINITION_VERSION = "mf772-r1-definitions-v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def code_identity(root: Path) -> tuple[str, str]:
    commit = _git_value(root, "rev-parse", "HEAD")
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", "src", "scripts", "metadata/field_mapping.csv"],
        cwd=root, check=True, capture_output=True,
    ).stdout
    return commit, hashlib.sha256(diff).hexdigest()


def write_artifact_metadata(
    artifact: Path,
    *,
    root: Path,
    run_id: str,
    stage: str,
    input_artifacts: list[Path],
    raw_manifest: Path,
    field_mapping: Path,
    validation_status: str,
    data_definition_version: str = R1_DEFINITION_VERSION,
    model_spec: Path | None = None,
) -> Path:
    commit, tree_hash = code_identity(root)
    payload = {
        "run_id": run_id,
        "stage": stage,
        "code_commit": commit,
        "code_tree_hash_or_dirty_diff_hash": tree_hash,
        "artifact": artifact.relative_to(root).as_posix(),
        "artifact_hash": sha256_file(artifact),
        "input_artifact_hashes": {
            path.relative_to(root).as_posix(): sha256_file(path) for path in input_artifacts
        },
        "raw_manifest_hash": sha256_file(raw_manifest),
        "field_mapping_hash": sha256_file(field_mapping),
        "data_definition_version": data_definition_version,
        "model_spec_hash": sha256_file(model_spec) if model_spec is not None else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": validation_status,
    }
    sidecar = artifact.with_suffix(artifact.suffix + ".metadata.json")
    sidecar.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return sidecar


def validate_artifact_metadata(
    artifact: Path,
    *,
    expected_stage: str = "R1",
    expected_definition_version: str = R1_DEFINITION_VERSION,
) -> dict:
    sidecar = artifact.with_suffix(artifact.suffix + ".metadata.json")
    if not sidecar.exists():
        raise ValueError(f"Artifact is missing required validation metadata: {sidecar}")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    if payload.get("stage") != expected_stage:
        raise ValueError(f"Artifact stage is {payload.get('stage')!r}, expected {expected_stage!r}")
    if payload.get("data_definition_version") != expected_definition_version:
        raise ValueError("Artifact uses an obsolete data-definition version")
    if payload.get("validation_status") != "PASS":
        raise ValueError(f"Artifact validation status is {payload.get('validation_status')!r}, expected 'PASS'")
    if payload.get("artifact_hash") != sha256_file(artifact):
        raise ValueError("Artifact hash does not match its validation metadata")
    return payload
