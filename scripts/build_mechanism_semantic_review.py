#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from llm_abm_sim.concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION

_REVIEW_FILENAME = "concurrent-message-mechanism-semantic-masters-v4-review.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or verify the deterministic six-master mechanism review set"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed bytes without writing",
    )
    return parser.parse_args()


def _review_packet() -> bytes:
    presentation = _MECHANISM_PRESENTATION.build()
    artifact_by_filename = {
        artifact.filename: artifact for artifact in presentation.mermaid_artifacts
    }
    lines = [
        "# Concurrent Message v4 机制语义母版低保真审批集",
        "",
        "Status: Awaiting whole-set human approval",
        "",
        "本文件是 canonical Final Research 网页之外的低保真审阅包。六图全部由 package-internal "
        "`concurrent_message_mechanism_presentation` Module 的唯一 Interface 确定性生成；当前 v1/v6 "
        "presentation 不读取本文件。",
        "",
        f"- Canonical semantic set identity: `{presentation.semantic_set_identity_sha256}`",
        "- Identity schema: `mechanism-semantic-set-v1`",
        "- Provider/API/image-generation calls: `0`",
        "- Review issue: [#185](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/185)",
        "",
        "## 整组审批合同",
        "",
        "批准必须来自一个 GitHub issue comment，并在同一 comment 中绑定批准人、批准时间、comment URL、"
        "上述 canonical semantic set identity，以及下表六个完整 filename/SHA-256。缺图、部分 hash、跨 comment "
        "拼接或任一 `.mmd` 后续 byte mutation 均不构成 approved set。在合法整组批准前，不得调用 image generation。",
        "",
        "| 顺序 | Mermaid master | SHA-256 |",
        "|---:|---|---|",
    ]
    for index, artifact in enumerate(presentation.mermaid_artifacts, start=1):
        lines.append(f"| {index} | `{artifact.filename}` | `{artifact.sha256}` |")

    lines.extend(("", "## 六图低保真预览", ""))
    for index, diagram in enumerate(presentation.diagrams, start=1):
        artifact = artifact_by_filename[diagram.filename]
        zh = next(
            projection for projection in diagram.projections if projection.language == "zh-CN"
        )
        en = next(
            projection for projection in diagram.projections if projection.language == "en-US"
        )
        lines.extend(
            (
                f"### {index}. {zh.value(diagram.title_key)} / {en.value(diagram.title_key)}",
                "",
                f"Master: `{diagram.filename}` · SHA-256: `{artifact.sha256}`",
                "",
                f"{zh.value(diagram.description_key)}<br>",
                en.value(diagram.description_key),
                "",
                "```mermaid",
                artifact.payload.decode().rstrip("\n"),
                "```",
                "",
                "<details>",
                "<summary>完整文本 fallback / Complete text fallback</summary>",
                "",
            )
        )
        for zh_value, en_value in zip(
            zh.fallback_values,
            en.fallback_values,
            strict=True,
        ):
            lines.append(f"- {zh_value} / {en_value}")
        lines.extend(
            (
                "",
                "</details>",
                "",
                "**Image brief**",
                "",
                f"- Raster generation required: `{'yes' if diagram.image_brief.generate_raster else 'no'}`",
                f"- Visual system: {diagram.image_brief.visual_system}",
                f"- Purpose: {diagram.image_brief.purpose}",
                f"- Composition: {diagram.image_brief.composition}",
                "- Required marks: " + "; ".join(diagram.image_brief.required_marks),
                "- Forbidden marks: " + "; ".join(diagram.image_brief.forbidden_marks),
                "",
            )
        )
    return ("\n".join(lines).rstrip() + "\n").encode()


def _expected_files(repo_root: Path) -> dict[Path, bytes]:
    presentation = _MECHANISM_PRESENTATION.build()
    asset_root = repo_root / "src" / "llm_abm_sim" / "report_assets"
    expected = {
        asset_root / artifact.filename: artifact.payload
        for artifact in presentation.mermaid_artifacts
    }
    expected[repo_root / "docs" / "references" / _REVIEW_FILENAME] = _review_packet()
    return expected


def main() -> int:
    args = _parse_args()
    repo_root = args.repo_root.resolve()
    expected = _expected_files(repo_root)
    if args.check:
        mismatches = [
            path
            for path, payload in expected.items()
            if not path.is_file() or path.read_bytes() != payload
        ]
        if mismatches:
            for path in mismatches:
                print(f"MISMATCH {path.relative_to(repo_root)}")
            return 1
        print(f"OK {len(expected)} deterministic mechanism review files")
        return 0

    for path, payload in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        print(path.relative_to(repo_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
