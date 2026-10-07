# 十话题 v17 最终发布验收

**结论：发布及验收通过。** Canonical：https://abm.q1ngyuan.top/ 。

- Release：`ten-topic-v17-20261007T113429Z`；完成时间UTC：`2026-10-07T12:11:13Z`。
- Worktree：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim`；分支：`codex/ten-topic-full-pool-replay`。00906d2的历史保留；原项目main仍bdedc9f，tracked diff=0。
- Release渲染/接纳提交：`5246a46d06a0809f0cd3e9b184bb7a48fecb060b`；最终部署执行器：`0bed76a`。后者只修复发布客户端通道，不改变已冻结报告/研究数据。
- Provider调用：**0**；没有重跑研究，没有修改论文，没有创建匿名仓库。没有读取/打印/写入模型凭证。客户端使用既有环境代理，未记录代理凭证。

## 正式来源与统计口径

|研究|明确正式来源|发布结果/单位|
|---|---|---|
|全样本|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-full-pool-20261006/main/`|109,200曝光；like63,420/comment5/share189/ignore45,586；实际互动63,614/109,200=58.255%；单次seed20260823|
|推荐参数|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-gpt-studies-20261006/formal-paths/`及formal-report|21×100行为seed=2,100路径；基准旧67.196%→新62.278%；新终点均值62.278%–65.848%|
|用户指标|同上；独立验收ten-topic-gpt-final-acceptance-20261007|原7×100=700路径；Local p99 rebuilt与新基准23/1000重合；fixed/rebuilt与共享baseline不冒充独立重复|
|四模型|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-four-model-20261007/`|16条件、28,800曝光；单次seed；共同初始panel配对bootstrap与自适应路径描述分开|

十个最终采集话题合并历史图，P95=5（全36,400 eligible pool参考）；holdout、建边、去重、累计权重不变。NI、邻居反馈和种子邻居补选使用新图；Local原全话题度数、Activity/Global既有口径不扩大。均值/区间基于行为seed，不是重复LLM判断。参数/指标普通Student-t df99区间与原Bonferroni家族分别披露。新DeepSeek为用户授权V4.1 Flash（旧V4 Flash）；Kimi一个显示模型；Gemini原网关alias/隐藏后端上下文可观测性限制保留。新旧共同改变网络、样本、服务时点，不作纯网络/指标/模型因果效应。

精确9来源绑定（全部原始eligibility字段保留；新v17独立接纳）：

|来源|绝对路径|SHA-256|
|---|---|---|
|whole_sample_manifest|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-full-pool-20261006/main/manifest.json`|`26b1bf7b796940952910ccfd78b5b259ff4f22ce48bf131f32be6a306300839d`|
|gpt_acceptance|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-gpt-final-acceptance-20261007/ACCEPTANCE.json`|`5df02d59afb8d287257554103af156724f890f5c2b5229ff583df3e10cf4a576`|
|gpt_inventory|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-gpt-final-acceptance-20261007/final-artifact-inventory.json`|`906637cc3997732c842996bf20b7d17911c57f8d2f4d2e6cffb3968e945935cd`|
|gpt_path_manifest|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-gpt-studies-20261006/formal-paths/manifest.json`|`d01006705b1ef826193b86d94c41741669f96b4626b6fd605ee7d505a0a123fa`|
|gpt_evidence|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-gpt-studies-20261006/formal-report/evidence.json`|`302d20eec48ab8c8d1dd61199fc048df9f8f61b2b002c54f0501f105485651e4`|
|four_model_acceptance|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-four-model-20261007/ACCEPTANCE_FINAL.json`|`0b17d7df5b0fd55d18ff648a3c7a917d3c86dd43e48ed37e63d5d984dd257831`|
|four_model_inventory|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-four-model-20261007/DELIVERY_INVENTORY.json`|`268471c4a479a60eb95298e06896e88089fa788841a4351d7163111c86d6d5c1`|
|four_model_bank_manifest|`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-four-model-20261007/final-bank/manifest.json`|`cbad2e56f7b615b47e40428bb83d52da43cd44a19f0b712e998e7595ac1aea98`|
|protected_v16_contract|`/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/sensitivity-v16-ticket-263-20260920/sensitivity-v16-20260920T113800Z-release-contract.json`|`6ef1f9baf777d29223fa1e9fab8d3cd1c86b368162f4f9f7491d86e83db63ef0`|

## 实际执行与独立性

- `scripts/validate_abm_report_release.py --require-formal-production`：退出0；显式9来源及全部原始artifact hashes核验，2,800路径/四模型80交付文件/旧v16 215文件接纳，264文件库存闭合。发布后再次验证退出0，见post-public-source-revalidation.txt。
- Workbook：artifact-tool生成17张表；ZIP/XML逐单元格与typed正式投影比对通过，含384条共同seed panel统计。没有公开新用户明细判断库、原始响应或凭证。
- 最终相关pytest：94 passed in66.55s，退出0；命令/完整输出preflight/final-tests.txt。范围为ten-topic Report/Release、Sensitivity/Parameter Report/Release、Deployment、既有Report validator及public-body verifier。
- 全src/tests/scripts py_compile、bash -n及新增/相关文件Ruff：退出0。
- 本地既有deployed-abm-report.spec.ts：1 passed(1.7m)。公网同一完整脚本：1 passed(2.2m)；1440/1600/390宽度、双语、过滤、旧版交互、下载HEAD、无console/page错误和无第三方请求通过。
- 部署事务：preflight→fresh旧current读回→candidate库存/健康→原子切换→公网正文/浏览器→加锁最终current/磁盘/容器读回，全部通过。
- 264公网HEAD；166完整正文SHA（64,753,330 bytes），98大历史文件按既有manifest-bound策略（1,721,373,543 bytes），没有宣称这98项公网完整正文重下载。
- 独立verify_publication.py不导入Report：解析实际HTML JSON和CSV复算排他行为分母/总数、21/7 n100、16条件28,800及384paired统计，并完整下载51份正文（全部47个新下载+报告/manifest+原历史HTML/manifest），全部SHA匹配。
- Report重建与工作簿source-cell验证共用typed投影，属于一致性复验，不冒充独立研究重跑。研究独立验收由绑定的前阶段原始产物验收提供。

## 修复与回退

修复共同seed面板CSV/工作簿缺项、JSON嵌入转义、历史容器手机宽度；补齐本地和远端exact v17 schema gate；显式客户端环境代理覆盖curl、browser与API HEAD。默认直连保留，TLS、完整字节数、SHA、重试及全部浏览器检查未削弱。

直连大正文停滞（140KiB后不再推进）和首次browser API HEAD未使用同一代理而超时，均保留原失败日志；自动真实回退v16后复核current、report/manifest SHA及容器healthy。随后同一immutable candidate重验、重新发布成功。见ROLLBACK_ACTUAL.txt及preflight/deploy-*-rollback.txt。旧v16 215文件全hash一致；新candidate保留旧HTML/manifest和其他原文件字节。scratch源码rollback也验证恢复旧Interface状态，退出0。未删除失败记录。早期未发布draft候选仍保留，不作为current来源。

## 留存/未执行及影响

- 全仓pytest不重复：此前约80分钟扫描停在旧纯mock恢复集成test_concurrent_recovery_parallel.py::test_parallel_acceptance_is_hash_bound_idempotent_and_zero_provider；本轮按发布Seam选择94项及完整公网suite，不把未跑全仓写成通过。
- 仓库要求的全域Ruff实际运行：42个既有错误（3个错误文件与00906d2逐字节一致）；新增/相关文件Ruff通过。pyright环境缺少.venv/bin/pyright，退出127，未执行。详情preflight/REPOSITORY_CHECK_CLASSIFICATION.json。
- 未新增Provider、未重跑四项研究/四模型、未做模型原生Gemini身份或隐藏上下文新探测、未改论文/匿名仓库。Mermaid spec人工语法检查，未安装额外parser；正式网页既有SVG机制及交互实测。
- 发布可用；这些既有工程/环境事项不影响已核验的正式统计、路径完整性及发布字节。正式聚合结果可进入论文更新和后续发布；须沿用上述条件性统计与共同变化限制，不宣称普遍稳健或单因素因果。

## 最终文件与hash

- formal_release_contract：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/ten-topic-v17-20261007T113429Z-release-contract.json`
  SHA-256：`5bad500cf5a1040ea04476cf16e151ed7bcbdd68146bfad699675463f0bb1380`
- report：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/ten-topic-v17-20261007T113429Z/report.html`
  SHA-256：`82012e17b4176284d21443cf07ba9a05336730864a27208cc7093da493186251`
- manifest：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/ten-topic-v17-20261007T113429Z/artifact_manifest.json`
  SHA-256：`e16f591b3cf18f2717137a4a21a726a299badaa208949d20e0cebe0c7574d479`
- workbook：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/ten-topic-v17-20261007T113429Z/ten-topic/ten-topic-research.xlsx`
  SHA-256：`abf1d40d1b67549a379d2ea4ccba49412a7b9266612a2837fbfafb526f3a51af`
- source_map：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/ten-topic-v17-20261007T113429Z/ten-topic/source-map.json`
  SHA-256：`285ef2159f0ffb7dc8040b5b9b4486202e582b6210540e549461d13fdff9f473`
- public_statistics：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/ten-topic-v17-20261007T113429Z/ten-topic/public-statistics.json`
  SHA-256：`d6a6f6a99b6f04428f072c0d0551bdfae7df446f335f0d4b8eef0b17fcfa3301`
- deployment_operation：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/DEPLOYMENT_OPERATION.json`
  SHA-256：`c1805f525ac555b4226c3300117099910af8d9de49251c6de058bd882eb36d68`
- independent_public_acceptance：`/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/runs/ten-topic-v17-publication-20261007/PUBLIC_ACCEPTANCE.json`
  SHA-256：`fd82a3d0e9d26862cc8e52e570c8eb4942cc65f1baa631040dee00fb46d8308f`

全部264文件绝对路径/hash在DELIVERY_INVENTORY.json；Public bodies逐文件在PUBLIC_ACCEPTANCE.json；契约和源码变更在CODE_DIFF.patch。Operational #264记录完整来源、release和验收。

## Changed files

- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/.gitignore`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/docs/architecture/README.md`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/docs/architecture/report-deployment.md`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/docs/architecture/ten-topic-report-release.md`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/docs/index.md`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/docs/references/README.md`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/docs/references/ten-topic-v17-canonical-release-20261007.md`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/playwright.config.ts`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/scripts/deploy_abm_report.sh`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/scripts/validate_abm_report_release.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/scripts/verify_abm_public_artifact_bodies.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/src/llm_abm_sim/concurrent_robustness_release.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/src/llm_abm_sim/concurrent_robustness_report.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/src/llm_abm_sim/report_deployment.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/src/llm_abm_sim/ten_topic_release.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/src/llm_abm_sim/ten_topic_report.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/tests/playwright/deployed-abm-report.spec.ts`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/tests/unit/test_public_artifact_acceptance.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/tests/unit/test_report_deployment.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/tests/unit/test_ten_topic_release.py`
- `/Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim/tests/unit/test_ten_topic_report.py`
