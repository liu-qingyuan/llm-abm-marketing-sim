"""v16: accession of two completed, hash-bound studies onto protected v15.

This is a publication contract, not a new experiment or a promotion of arbitrary
reports. Only the reviewed final artifacts below are accepted. Their original
eligibility flags and historical deployment statements are retained unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import statistics
import tempfile
from pathlib import Path
from typing import Any

from .concurrent_robustness_report import _REPORT_PRESENTATION
from .concurrent_robustness_revised import inventory, json_bytes, sha
from .revised_robustness_release import ENDPOINT, _inside
from .sensitivity_report import index_curve_svg

SCHEMA = "abm-report-release-contract-v16"
PURPOSE = "protected_v15_with_completed_sensitivity_research"
BASELINE_SHA = "16381a61677bce3ac09cd85053810fe66d909ce36155f0455b4d3c46a2be5bb9"
PARAMETER_SHA = "87a3eb404c2e378b69347b67172fce684bf597b8bbc439e265c9d67411e7b0a4"
INDEX_SHA = "7ea3ee1a3cffcb2ecb3a48161b509b94966149d50ca2c385235003c0d23420e7"
_FIELDS = {"schema_version", "release_purpose", "release_id", "source_directory",
           "implementation_commit", "canonical_endpoint", "sources", "artifact_sha256",
           "release_identity_sha256", "production_deploy_eligible", "provider_calls"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _bound(path: Path, expected: str) -> bytes:
    if not path.is_file() or path.is_symlink() or path.absolute() != path.resolve() or sha(path) != expected:
        raise ValueError(f"Sensitivity source hash or regular-file identity drift: {path}")
    return path.read_bytes()


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _check_statistics(parameter: Path, index: Path) -> None:
    """Check published units/means against path tables; never run the simulator."""
    p = json.loads((parameter / "evidence.json").read_bytes())
    i = json.loads((index / "evidence.json").read_bytes())
    if (p["paths"], p["exposures"], p["barriers"]) != (2100, 3780000, 63000):
        raise ValueError("Parameter evidence scope crossed")
    if (i["independently_verified_paths"], i["verified_exposures"], i["verified_barriers"]) != (700, 1260000, 21000):
        raise ValueError("Index evidence scope crossed")
    if p["production_deploy_eligible"] is not False or i["production_deploy_eligible"] is not False:
        raise ValueError("Original independent eligibility must remain unchanged")
    paths = _csv(parameter / "path-summary.csv")
    expected_seeds = {str(n) for n in range(2026091700, 2026091800)}
    expected_configs = {f"w{w}-h{h}" for w in range(7) for h in (1, 3, 6)}
    if len(paths) != 2100 or {(r['configuration'], r['seed']) for r in paths} != {(c, s) for c in expected_configs for s in expected_seeds}:
        raise ValueError("Parameter path matrix crossed")
    metrics = _csv(index / "path-metrics.csv")
    arms = {"baseline", "activity_weights", "activity_p99", "local_weights_fixed", "local_weights_rebuilt", "local_p99_fixed", "local_p99_rebuilt"}
    messages = {"message_1", "message_2", "message_3", "all"}
    if len(metrics) != 2800 or {(r['arm'], r['seed'], r['message']) for r in metrics} != {(a, s, m) for a in arms for s in expected_seeds for m in messages}:
        raise ValueError("Index path matrix crossed")
    for row in metrics:
        exposures = 1800 if row['message'] == 'all' else 600
        if int(row['exposures']) != exposures or sum(int(row[a]) for a in ('like', 'comment', 'share')) != int(row['engagement']):
            raise ValueError("Index integer actions or denominator crossed")
        if abs(float(row['engagement_rate']) - int(row['engagement']) / exposures) > 1e-12:
            raise ValueError("Index rate crossed")
    for estimate in _csv(index / 'arm-estimates.csv'):
        values = [float(r[estimate['metric']]) for r in metrics if r['arm'] == estimate['arm'] and r['message'] == estimate['message']]
        if int(estimate['n']) != 100 or abs(statistics.mean(values) - float(estimate['mean'])) > 1e-10:
            raise ValueError("Index mean is not the 100-path mean")
    baseline = {(r['seed'], m): float(r[m]) for r in paths if r['configuration'] == 'w0-h3' for m in messages - {'all'}}
    if any(float(r['engagement_rate']) != baseline[r['seed'], r['message']] for r in metrics if r['arm'] == 'baseline' and r['message'] != 'all'):
        raise ValueError("Baseline replication crossed")


def _materialize(root: Path, sources: dict[str, str], release_id: str, commit: str):
    if set(sources) != {'protected_v15_contract', 'parameter_manifest', 'index_audit'}:
        raise ValueError('Sensitivity source bindings crossed')
    baseline_path = _inside(root, sources['protected_v15_contract'])
    parameter_manifest = _inside(root, sources['parameter_manifest'])
    index_audit = _inside(root, sources['index_audit'])
    old = json.loads(_bound(baseline_path, BASELINE_SHA))
    pm = json.loads(_bound(parameter_manifest, PARAMETER_SHA))
    ia = json.loads(_bound(index_audit, INDEX_SHA))
    baseline = _inside(root, old['source_directory'])
    if {k: v['sha256'] for k, v in inventory(baseline).items()} != old['artifact_sha256']:
        raise ValueError('Protected v15 inventory drift')
    downloads = {}
    for name, digest in pm['sha256'].items():
        downloads['parameter/' + name] = _bound(parameter_manifest.parent / name, digest)
    downloads['parameter/artifact-manifest.json'] = parameter_manifest.read_bytes()
    for name, digest in ia['artifacts'].items():
        payload = _bound(index_audit.parent / name, digest)
        # Publish report/evidence/aggregate data only, never collector code/ledgers.
        if name.endswith(('.csv', '.json')) or name in {'report.html', 'REPORT.md', 'PROTOCOL.md'}:
            downloads['index-sensitivity/' + name] = payload
    downloads['index-sensitivity/completion-audit.json'] = index_audit.read_bytes()
    downloads['index-sensitivity/curves.svg'] = index_curve_svg(downloads['index-sensitivity/report.html'])
    _check_statistics(parameter_manifest.parent, index_audit.parent)
    report = _REPORT_PRESENTATION.render_sensitivity_research((baseline / 'report.html').read_bytes(), release_id=release_id)
    content = {k: v for k, v in old['artifact_sha256'].items() if k not in {'report.html', 'artifact_manifest.json'}}
    if set(content) & set(downloads):
        raise ValueError('New downloads overlap protected content')
    content.update({k: hashlib.sha256(v).hexdigest() for k, v in downloads.items()})
    content['report.html'] = hashlib.sha256(report).hexdigest()
    identity = _digest({'schema': SCHEMA, 'release_id': release_id, 'implementation_commit': commit, 'sources': sources, 'content_sha256': content})
    old_manifest = json.loads((baseline / 'artifact_manifest.json').read_bytes())
    approved = old_manifest['approved_downloads']
    if isinstance(approved, dict):
        approved = list(approved.values())
    manifest = {'schema_version': 'abm-report-release-manifest-v16', 'release_contract_schema': SCHEMA,
                'release_id': release_id, 'release_identity_sha256': identity, 'implementation_commit': commit,
                'production_deploy_eligible': True, 'provider_calls': 0, 'content_sha256': content,
                'approved_downloads': sorted(set(approved) | set(downloads)),
                'protected_v15_release_identity': old['release_identity_sha256']}
    files = {**downloads, 'report.html': report, 'artifact_manifest.json': json_bytes(manifest)}
    hashes = {**content, 'artifact_manifest.json': _digest(manifest)}
    return baseline, files, hashes, identity


def promote_sensitivity_release(*, repo_root: str | Path, protected_v15_contract: str | Path,
                                parameter_manifest: str | Path, index_audit: str | Path,
                                destination_dir: str | Path, release_id: str, implementation_commit: str) -> Path:
    """Copy exact completed studies into a new immutable v16; never deploy or call Provider."""
    root = Path(repo_root).resolve()
    destination = _inside(root, destination_dir)
    contract_path = destination.with_name(destination.name + '-release-contract.json')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', release_id) or not re.fullmatch(r'[0-9a-f]{40}', implementation_commit):
        raise ValueError('Invalid release identity')
    sources = {key: str(_inside(root, value)) for key, value in {
        'protected_v15_contract': protected_v15_contract, 'parameter_manifest': parameter_manifest, 'index_audit': index_audit}.items()}
    if destination.exists() or contract_path.exists() or any(destination.is_relative_to(Path(p).parent) or Path(p).is_relative_to(destination) for p in sources.values()):
        raise ValueError('Output exists or overlaps source')
    baseline, files, hashes, identity = _materialize(root, sources, release_id, implementation_commit)
    if destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError('Output overlaps protected release')
    contract = dict(schema_version=SCHEMA, release_purpose=PURPOSE, release_id=release_id,
                    source_directory=str(destination), implementation_commit=implementation_commit,
                    canonical_endpoint=ENDPOINT, sources=sources, artifact_sha256=hashes,
                    release_identity_sha256=identity, production_deploy_eligible=True, provider_calls=0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.v16-', dir=destination.parent))
    installed_contract = False
    try:
        shutil.copytree(baseline, staging, dirs_exist_ok=True)
        for directory in [staging, *(p for p in staging.rglob('*') if p.is_dir())]:
            directory.chmod(0o755)
        for name, payload in files.items():
            p = staging / name
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                p.chmod(0o644)
            p.write_bytes(payload)
        if {k: v['sha256'] for k, v in inventory(staging).items()} != hashes:
            raise ValueError('Staged inventory drift')
        for p in staging.rglob('*'):
            if p.is_file():
                p.chmod(0o444)
        with contract_path.open('xb') as stream:
            installed_contract = True
            stream.write(json_bytes(contract))
        contract_path.chmod(0o444)
        os.rename(staging, destination)
    except BaseException:
        if installed_contract:
            contract_path.unlink()
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return contract_path


def validate_sensitivity_release(*, repo_root: str | Path, contract_document: dict[str, Any],
                                 source_dir: str | Path, snapshot_dir: str | Path | None = None) -> dict[str, Any]:
    """Rebuild the publication from pinned completed evidence, rejecting altered copies."""
    c = dict(contract_document)
    if set(c) != _FIELDS or c['schema_version'] != SCHEMA or c['release_purpose'] != PURPOSE or c['canonical_endpoint'] != ENDPOINT or c['production_deploy_eligible'] is not True or c['provider_calls'] != 0:
        raise ValueError('Invalid sensitivity contract')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', c['release_id']) or not re.fullmatch(r'[0-9a-f]{40}', c['implementation_commit']):
        raise ValueError('Invalid sensitivity identity')
    root = Path(repo_root).resolve()
    source = _inside(root, source_dir)
    if str(source) != c['source_directory']:
        raise ValueError('Sensitivity source directory crossed')
    _, _, hashes, identity = _materialize(root, c['sources'], c['release_id'], c['implementation_commit'])
    if hashes != c['artifact_sha256'] or identity != c['release_identity_sha256']:
        raise ValueError('Sensitivity declarations drift')
    for folder in [source, *([Path(snapshot_dir)] if snapshot_dir else [])]:
        if {k: v['sha256'] for k, v in inventory(folder).items()} != hashes:
            raise ValueError('Sensitivity physical inventory drift')
    return {**c, 'formal_research_evidence': True, 'realized_source_identity': identity,
            'report_sha256': hashes['report.html'], 'manifest_sha256': hashes['artifact_manifest.json'],
            'sampling_method': 'separate_protected_full_pool_and_1000_user_studies',
            'sampling_status': 'completed_sensitivity_studies_fixed_and_rebuilt_samples',
            'decision_execution_mode': 'persisted_formal_evidence_zero_provider_publication'}


def require_sensitivity_deployment_profile(result: dict[str, Any]) -> dict[str, Any]:
    """Project validated publication facts; no statistics belong to Deployment."""
    if result.get('schema_version') != SCHEMA or result.get('formal_research_evidence') is not True or result.get('production_deploy_eligible') is not True or result.get('provider_calls') != 0:
        raise ValueError('v16 requires validated completed sensitivity evidence')
    return {'realized_source_identity': result['realized_source_identity'], 'release_readiness': {
        'schema_version': 'sensitivity-v16-release-readiness-v1', 'release_contract_schema': SCHEMA,
        'release_id': result['release_id'], 'realized_source_identity': result['realized_source_identity'],
        'canonical_endpoint': ENDPOINT, 'provider_calls': 0, 'operational_authorization_required': True,
        'deployment_authorized': False, 'public_acceptance_recorded': False}}
