from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest

Reader = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/verify_ten_topic_preservation.py'))['PreservedSources']


def fixture(tmp_path: Path):
    old = tmp_path / 'removed-worktree'
    main = tmp_path / 'main'
    main.mkdir()
    target = main / 'contract.json'
    original = json.dumps({'historical_root': str(old), 'source_identity': 'unchanged'}).encode()
    target.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    manifest = main / 'copy.json'
    manifest.write_text(json.dumps([{'original_path': str(old / 'contract.json'), 'persistent_path': str(target), 'kind': 'file', 'sha256': digest, 'bytes': len(original)}]))
    mapping = main / 'mapping.json'
    mapping.write_text(json.dumps({'schema_version': 'ten-topic-preservation-map-v1', 'main_root': str(main), 'historical_root': str(old), 'routes': [{'original_prefix': str(old), 'persistent_prefix': str(main)}], 'exact_overrides': {}, 'copy_manifest': str(manifest), 'copy_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    return Reader(mapping), old, target, original, manifest


def test_removed_worktree_is_readable_without_rewriting_contract(tmp_path: Path):
    reader, old, target, original, _ = fixture(tmp_path)
    assert not old.exists()
    assert reader.verify_copy()['objects'] == 1
    assert reader.path(old / 'contract.json') == target
    assert target.read_bytes() == original


def test_changed_destination_is_rejected(tmp_path: Path):
    reader, _, target, _, _ = fixture(tmp_path)
    target.write_text('altered')
    with pytest.raises(ValueError, match='identity mismatch'):
        reader.verify_copy()


def test_inventory_tampering_is_rejected(tmp_path: Path):
    reader, _, _, _, manifest = fixture(tmp_path)
    manifest.write_text('[]')
    with pytest.raises(ValueError, match='inventory identity'):
        Reader(manifest.parent / 'mapping.json')


def test_unmapped_or_traversal_pointer_is_rejected(tmp_path: Path):
    reader, old, _, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match='outside preserved'):
        reader.path(tmp_path / 'outside')
    with pytest.raises(ValueError, match='normalized'):
        reader.path(old / '..' / 'outside')
