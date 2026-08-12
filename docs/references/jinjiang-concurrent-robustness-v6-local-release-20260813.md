# Concurrent Robustness v6 本地发布交接（2026-08-13）

## 状态

- operational Ticket：[#181](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/181)
- 实现 commit：`ca638f44ef7424e3991c60ab1c1affc2144eec46`
- 状态：**reviewed local production release ready；未部署 canonical**
- Provider/API/image-generation calls：`0`
- secrets 读取、打印或写入：否
- SSH / remote switch：未执行
- 本次 preflight 时 canonical `report.html` SHA-256：`541bcf04820c8643c73ca9e7d927fe6a1d44c23d02f849532bcb18ab6c5eeb43`

> 独立 review 后，`528dfb7` 加强了 candidate content identity、strict zero-call accounting 与 closure-download exclusion。原 local release 已删除；以下路径与 hashes 已按该 commit 全链重建并重新验收。

## 显式 lineage

- Historical Concurrent Formal：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/`
- Historical robustness workspace：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace/`
- immutable study root：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace.study-root/`
- Formal contracts：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-contracts/`
- historical candidate：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-report-candidate/`
- presentation candidate：`runs/jinjiang-concurrent-robustness-report-candidate-v3-reviewed-20260813T000000Z/`
- presentation closure：`runs/jinjiang-concurrent-robustness-presentation-closure-v1-reviewed-20260813T000000Z.json`
- immutable production source：`runs/jinjiang-concurrent-robustness-production-v6-reviewed-20260813T000000Z/`
- release contract：`runs/jinjiang-concurrent-robustness-production-v6-reviewed-20260813T000000Z-release-contract.json`
- physical snapshot：`runs/jinjiang-concurrent-robustness-production-v6-reviewed-20260813T000000Z-physical-snapshot/`

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

- closure SHA-256：`a58fff6d50ae735e100401cb571084862ea5540df7b8515f1847755caac9937e`
- release id：`jinjiang-concurrent-robustness-v6-reviewed-20260813T000000Z`
- release schema：`abm-report-release-contract-v6`
- production report：`ca476e617db2096a9b4511c8143c7bf48f22574d228e60ed483d48fed63beca0`
- production manifest：`e7d0219dc97b1d1f84592fc91c08d51f1682c80654e90a7f3c8f9e7681374b1f`
- production release identity：`8ac9a0c1f7df9d6f7ca029c6454fd82b5dff596e44f98abc174a97c662c36d64`
- production inventory：42 files
- snapshot inventory digest：`6b4bbbc1faad2c2e68df330b730a2c9dae4f044ac9785464d979e613934f62fc`

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

[#182](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/182) 必须只使用本页 reviewed 显式 contract/source/release id。部署前重新读取 remote `current` 作为 rollback identity，并使用 Deployment Module 的 physical snapshot、candidate health、atomic switch、rollback 和逐 artifact public acceptance，不得扫描“最新”目录。
