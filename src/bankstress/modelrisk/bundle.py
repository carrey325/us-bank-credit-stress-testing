"""Hash-bound local research bundles. Never mutate a sealed bundle."""
from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from bankstress.artifacts import sha256_file, validate_artifact_metadata

SCHEMA_VERSION = 1
ARCHIVE_INPUTS = {
    'model_panel.parquet': 'data/derived/model_panel.parquet',
    'macro_history.parquet': 'data/derived/macro_panel_final.parquet',
    'ar_predictions.parquet': 'outputs/models/ar/predictions.parquet',
    'fe_predictions.parquet': 'outputs/models/dynamic_fe/predictions.parquet',
    'quantile_predictions.parquet': 'outputs/validation/oos_predictions.parquet',
    'quantile_diagnostics.csv': 'outputs/validation/quantile_fit_diagnostics.csv',
    'stress_paths.parquet': 'outputs/stress/stress_paths.parquet',
    'macro_timing.csv': 'outputs/stress/macro_predictor_timing.csv',
    'fed_scenarios.parquet': 'data/external/fed_2026_scenarios.parquet',
    'model_use_registry.json': 'outputs/validation/model_use_registry.json',
}


def write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def new_run(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id):
        raise ValueError('invalid run_id')
    target = root / run_id
    target.mkdir(parents=True, exist_ok=False)
    return target


def seal_bundle(directory: Path, metadata: dict) -> dict:
    if (directory / 'manifest.json').exists():
        raise ValueError('bundle already sealed')
    files = {p.relative_to(directory).as_posix(): sha256_file(p)
             for p in sorted(directory.rglob('*')) if p.is_file()}
    payload = {**metadata, 'schema_version': SCHEMA_VERSION, 'files': files,
               'created_at': datetime.now(timezone.utc).isoformat()}
    write_json(directory / 'manifest.json', payload)
    return payload


def verify_bundle(directory: Path) -> dict:
    directory = directory.resolve()
    payload = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if payload.get('schema_version') != SCHEMA_VERSION or not payload.get('files'):
        raise ValueError('unsupported or empty bundle manifest')
    for relative in payload['files']:
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or relative == 'manifest.json':
            raise ValueError('unsafe manifest path')
    for relative, expected in payload['files'].items():
        path = directory / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f'bundle hash mismatch: {relative}')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual != set(payload['files']) | {'manifest.json'}:
        raise ValueError('unregistered bundle files')
    return payload


def verify_linked(child: Path, parent: Path, field: str) -> dict:
    verify_bundle(parent)
    payload = verify_bundle(child)
    if payload.get(field) != sha256_file(parent / 'manifest.json'):
        raise ValueError('bundle lineage does not bind the supplied parent')
    return payload


def code_record(root: Path) -> dict:
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
                            capture_output=True, text=True).stdout.strip()
    sources = {p.relative_to(root).as_posix(): sha256_file(p)
               for base in ('src', 'scripts', 'configs') for p in sorted((root / base).rglob('*'))
               if p.is_file() and p.suffix in ('.py', '.yaml', '.toml')}
    packages = {name: importlib.metadata.version(name)
                for name in ('numpy', 'pandas', 'pyarrow', 'statsmodels', 'scikit-learn')}
    return {'code_commit': commit, 'source_hashes': sources, 'packages': packages}


def freeze_archive(archive: Path, directory: Path, root: Path, metadata: dict) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    lineage = {}
    for name, relative in ARCHIVE_INPUTS.items():
        source = archive / relative
        sidecar = json.loads(source.with_suffix(source.suffix + '.metadata.json').read_text())
        stage = 'R3' if relative.startswith('outputs/validation/') else (
            'R4' if relative.startswith(('outputs/stress/', 'data/external/')) else 'R2')
        validate_artifact_metadata(source, expected_stage=stage)
        lineage[name] = sidecar
        shutil.copyfile(source, directory / name)
        if sha256_file(directory / name) != sidecar['artifact_hash']:
            raise ValueError(f'archive changed during freeze: {name}')
    for name in ('model_specs.yaml', 'macro_series.yaml', 'stress_specs.yaml'):
        shutil.copyfile(root / 'configs' / name, directory / name)
    spec_hash = sha256_file(directory / 'model_specs.yaml')
    for name, sidecar in lineage.items():
        if sidecar.get('model_spec_hash') and sidecar['model_spec_hash'] != spec_hash:
            raise ValueError(f'historical model specification differs: {name}')
        for parent_name, parent_relative in ARCHIVE_INPUTS.items():
            expected = sidecar.get('input_artifact_hashes', {}).get(parent_relative)
            if expected and sha256_file(directory / parent_name) != expected:
                raise ValueError(f'historical input lineage mismatch: {name} -> {parent_name}')
    write_json(directory / 'historical_lineage.json', lineage)
    return seal_bundle(directory, {**metadata, **code_record(root),
                                  'object_type': 'HISTORICAL_INPUTS_NOT_FITTED_MODELS'})
