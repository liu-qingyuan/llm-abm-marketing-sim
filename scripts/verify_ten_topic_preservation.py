"""Read-only relocation verification; never rewrites historical research contracts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class PreservedSources:
    """Translate physical locations only; original IDs, JSON and hashes stay intact."""

    def __init__(self, mapping_file: Path):
        self.document = json.loads(mapping_file.read_bytes())
        if self.document['schema_version'] != 'ten-topic-preservation-map-v1':
            raise ValueError('Unsupported preservation map')
        self.root = Path(self.document['main_root']).resolve()
        self.manifest = Path(self.document['copy_manifest'])
        if sha256(self.manifest) != self.document['copy_manifest_sha256']:
            raise ValueError('Preservation inventory identity drift')
        self.entries = json.loads(self.manifest.read_bytes())

    def path(self, original: str | Path) -> Path:
        old = Path(original)
        if not old.is_absolute() or '..' in old.parts:
            raise ValueError('Absolute normalized historical path required')
        override = self.document['exact_overrides'].get(str(old))
        if override:
            target = Path(override)
        else:
            target = old
            for route in sorted(self.document['routes'], key=lambda r: len(r['original_prefix']), reverse=True):
                prefix = Path(route['original_prefix'])
                if old.is_relative_to(prefix):
                    target = Path(route['persistent_prefix']) / old.relative_to(prefix)
                    break
        if not target.is_relative_to(self.root) or '..' in target.parts:
            raise ValueError('Historical pointer is outside preserved project')
        return target

    def check(self, original: str | Path, expected: str) -> Path:
        path = self.path(original)
        if path.is_symlink() or not path.is_file() or sha256(path) != expected:
            raise ValueError(f'Preserved artifact identity mismatch: {path}')
        return path

    def verify_copy(self) -> dict[str, int]:
        for entry in self.entries:
            if self.path(entry['original_path']) != Path(entry['persistent_path']):
                raise ValueError('Copy inventory and location map disagree')
            if entry['kind'] == 'file':
                self.check(entry['original_path'], entry['sha256'])
            else:
                path = self.path(entry['original_path'])
                if not path.is_symlink() or os.readlink(path) != entry['target'] or not path.exists():
                    raise ValueError('Preserved symlink identity or target drift')
        return {'objects': len(self.entries), 'bytes': sum(r.get('bytes', 0) for r in self.entries)}

    def verify_research(self) -> dict[str, Any]:
        """Check original inventories through the map, not a relocated/fabricated contract."""
        old = Path(self.document['historical_root'])
        publication = old / 'runs/ten-topic-v17-publication-20261007'
        location = json.loads(self.path(publication / 'RELEASE_LOCATION.json').read_bytes())
        contract_path = self.path(location['contract'])
        contract = json.loads(contract_path.read_bytes())
        operation = json.loads(self.path(publication / 'DEPLOYMENT_OPERATION.json').read_bytes())
        if (contract['schema_version'] != 'abm-report-release-contract-v17'
                or sha256(contract_path) != operation['plan']['contract_sha256']
                or contract['release_id'] != operation['plan']['release_id']):
            raise ValueError('Published historical contract identity drift')
        for name, expected in contract['artifact_sha256'].items():
            self.check(Path(contract['source_directory']) / name, expected)
        sources = {}
        for name, reference in contract['sources'].items():
            sources[name] = json.loads(self.check(reference['path'], reference['sha256']).read_bytes())
        main_root = Path(contract['sources']['whole_sample_manifest']['path']).parent
        for row in sources['whole_sample_manifest']['artifacts']:
            self.check(main_root / row['relative_path'], row['sha256'])
        for name, expected in sources['gpt_inventory']['final_objects'].items():
            self.check(name, expected)
        gpt_root = Path(contract['sources']['gpt_path_manifest']['path']).parent
        for name, expected in sources['gpt_path_manifest']['paths'].items():
            self.check(gpt_root / name, expected)
        for row in sources['four_model_inventory']:
            self.check(row['path'], row['sha256'])
        historical = sources['protected_v16_contract']
        for name, expected in historical['artifact_sha256'].items():
            self.check(Path(historical['source_directory']) / name, expected)
        self.check(contract['workbook']['path'], contract['workbook']['sha256'])
        if (len(sources['gpt_path_manifest']['paths']) != 2800
                or sources['gpt_acceptance']['status'] != 'pass'
                or sources['four_model_acceptance']['conditions'] != 16):
            raise ValueError('Historical formal scope drift')
        return {'release_id': contract['release_id'], 'release_files': len(contract['artifact_sha256']),
                'source_bindings': len(sources), 'gpt_paths': 2800,
                'four_model_delivery_files': len(sources['four_model_inventory']),
                'protected_v16_files': len(historical['artifact_sha256']),
                'historical_contract_sha256': sha256(contract_path), 'historical_identity_rewritten': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--resolve', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        sources = PreservedSources(args.mapping)
        if args.resolve:
            entry = next(r for r in sources.entries if r['original_path'] == str(args.resolve))
            if entry['kind'] != 'file':
                raise ValueError('Resolve requires a preserved regular artifact')
            target = sources.check(args.resolve, entry['sha256'])
            print(json.dumps({'original_path': str(args.resolve), 'persistent_path': str(target), 'sha256': entry['sha256']}))
            return 0
        result = {'schema_version': 'ten-topic-preservation-verification-v1', 'status': 'pass',
                  'copy': sources.verify_copy(), 'research': sources.verify_research(), 'provider_calls': 0}
        if args.output:
            if args.output.exists():
                raise ValueError('Verification output must be new')
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        print(f'preservation verification failed: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
