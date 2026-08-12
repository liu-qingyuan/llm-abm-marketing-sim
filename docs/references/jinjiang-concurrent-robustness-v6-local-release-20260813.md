# Concurrent Robustness v6 本地发布交接（2026-08-13）

## 状态

- operational Ticket：[#181](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/181)
- 实现 commit：`ca638f44ef7424e3991c60ab1c1affc2144eec46`
- 状态：**local production release ready；未部署 canonical**
- Provider/API/image-generation calls：`0`
- secrets 读取、打印或写入：否
- SSH / remote switch：未执行
- 本次 preflight 时 canonical `report.html` SHA-256：`541bcf04820c8643c73ca9e7d927fe6a1d44c23d02f849532bcb18ab6c5eeb43`

## 显式 lineage

- Historical Concurrent Formal：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/`
- Historical robustness workspace：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace/`
- immutable study root：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace.study-root/`
- Formal contracts：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-contracts/`
- historical candidate：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-report-candidate/`
- presentation candidate：`runs/jinjiang-concurrent-robustness-report-candidate-v3-20260813T000000Z/`
- presentation closure：`runs/jinjiang-concurrent-robustness-presentation-closure-v1-20260813T000000Z.json`
- immutable production source：`runs/jinjiang-concurrent-robustness-production-v6-20260813T000000Z/`
- release contract：`runs/jinjiang-concurrent-robustness-production-v6-20260813T000000Z-release-contract.json`
- physical snapshot：`runs/jinjiang-concurrent-robustness-production-v6-20260813T000000Z-physical-snapshot/`

## Candidate identity

- candidate identity：`b44e2831e9604fb885625fcb7dd0a488a796e68e5cae12eff15982555ff9b07f`
- manifest：`1adcba97bbf209e9b430e38dec53f2d9d360fcbd0221bac58e097b9babff1f94`
- `report.html`：`b9cb2f05fb38463f408fe8d29dbfa1c546aa874b2db5ebbd4ed64b651042c421`
- report payload：`fddaf5c4565168f299405d1f7c6660da34255a79e41bba9e98a8a575984ea2b3`
- release evidence：`90f36138be24919a6eb8bba473ed934c80c9f41bdd6d2bafd496455fa57af299`
- candidate content identity：`737639e383c02f3fb455a1b03fd82284f93a140f56756d51b3ce3233781f0511`
- `report.html` size：`2,456,615` bytes（小于 3 MiB）
- candidate eligibility：`production_deploy_eligible=false`

## Closure 与 production identity

- closure SHA-256：`77ead19dbc001c512c6537f60b0f9979bbd3d5a2a3aa874e1e04e86991b9f793`
- release id：`jinjiang-concurrent-robustness-v6-20260813T000000Z`
- release schema：`abm-report-release-contract-v6`
- production report：`eb97b590ef6b061e87d17a2a8bb024bd8c8fd94d14327dd3046aeccdc287eb52`
- production manifest：`e321c8819cdcfe62df2df07134068ae1fb49ea8089abc08989b5623cf91cfb5a`
- production release identity：`9d7d84cb85034539b8a178edb19a4ba6f76ca4067914212fdd66694b470f6b8c`
- production inventory：42 files
- snapshot inventory digest：`271b1c14ec6981325400a1cac5a7d4aac7118af8bf1e3bcedb5442256fdb5a85`

`presentation_closure_contract.json` 是 production inventory/release identity 的 regular artifact；它不是 Report approved download。production copy 与独立 closure bytes 相同。

## Validation evidence

通过：

- candidate compose 与 Report closure；
- `concurrent-robustness-presentation-closure-contract-v1` validation；
- v6 promotion；
- standalone validator + `--require-formal-production`；
- physical snapshot validator；
- source/snapshot 42-file contract hash exact match；
- actual candidate + production Playwright：desktop/mobile、双语、三张 semantic diagrams、Prompt disclosure、trace ready/filter/pagination/drawer、三个 `.mmd` 和 approved downloads；无 third-party request、console error 或 page error；
- implementation suite：`651 passed, 2 deselected`；
- immutable Formal/study/contracts/historical candidate 共 112 个输入文件前后 SHA-256 完全不变；旧 semantic candidate v2 的四个主 hash 也保持不变。

## Deployment handoff

[#182](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/182) 必须只使用上述显式 release contract、source directory 和 release id。部署前重新读取 remote `current` 作为 rollback identity；使用 Deployment Module 的 physical snapshot、candidate health、atomic switch、rollback 和逐 artifact public acceptance，不得扫描“最新”目录。
