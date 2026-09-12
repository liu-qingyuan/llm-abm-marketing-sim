# 四模型恢复稳健性分析 v15 canonical 发布

- 公网：[Final Research](https://abm.q1ngyuan.top/)，保留现有网页结构、Full-Pool、Historical、Primary/Shadow、排序权重及旧GPT析因证据；增加独立跨厂商恢复分析。
- Release：`revised-four-model-v15-20260912T105000Z`；部署时间：`2026-09-12T16:41:27Z`。
- Report/Analysis implementation：`a747bb50fa0a4f597d97892797044fd932329b24`；部署回读修复：`c02ca1a4fe930bd03ec6a95585e67df7fb280c1c`。
- Source：`/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified`；原 Evidence SHA256：`a7407bf355d6049af8667a69b540fe2b29591d7f8e7ef71d6cb08d01fee72b17`。
- 原plan：`/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/concurrent-robustness-recovery-formal-20260909T213305Z/plan.json`，SHA256 `2d64026ce755a5a5c3e8dd42f6c74add7dc1435b42adef3cbc47dac030da9b16`；HEAD sequence134884 / `a28681fbaf27c90552dd4a8c4e410696353e99ff18dc176d6ec5a41872311977`。
- Immutable release：`/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/revised-four-model-v15-ticket-250-20260912/revised-four-model-v15-20260912T105000Z`；contract SHA256 `16381a61677bce3ac09cd85053810fe66d909ce36155f0455b4d3c46a2be5bb9`。
- Release identity：`f44b565098aeedabdf503b45572d5f5e965d782d6f2e0d3bb421104438a1094a`。
- Report SHA256：`085a572c55bc88f5a8956f87ac731802e6866a9e3c81456266757402147de44e`；manifest SHA256：`5f78009bc3ab80fd80299dcb0dfe366ecef8e615bd4e3704bf692124f36d5cb0`。
- 同源分析：[analysis.json](https://abm.q1ngyuan.top/revised-robustness/analysis.json)，[evidence.json](https://abm.q1ngyuan.top/revised-robustness/evidence.json)。

## 验收

161个文件完整清单；146个旧证据文件bytes不变；13个新增下载。独立校验48个图面板、16行结果表、2320行CSV与JSON一致。部署使用显式contract/source/release id；独立重放账本、local snapshot、fresh rollback、候选health、锁内原子current、全部公网HEAD、合同body-hash策略、三个viewport Playwright及最终锁内readback均通过。

120项相关回归通过；新增调用Provider=0；原证据18files及weekly2files bytes/mode保留。全量pytest在既有慢速offline recovery integration中约20分钟后中止，未宣称全套通过；全仓Ruff存在42项既有问题（3个文件与baseline逐bytes一致），pyright未安装。修改范围Ruff/编译/bash语法检查通过。

原部署脚本的最终readback引用未定义变量，在远端写入前发现并中止第一次preflight；仅修复部署执行器、增加bash nounset回归，首次修复后的发布完整通过；随后以另一immutable release澄清中英文历史总说明，原release保留且分析及13个新增下载bytes完全一致。

## 口径与回退

本次仅28800/16cells/480barriers，原五模型36000/20/600不标完成。仅Batch0共享20seedusers×3messages进行直接配对；后续路径、主效应与交互描述性展示。Kimi33订阅k3-256k+7167官方kimi-k3；108已知失败和5archived unknown保留，历史token总额仍null。原交付eligibility=false不翻转，v15以独立闭合Formal证据合同发布。

保留生产回退点`revised-four-model-v15-20260912T102200Z`；副本回退测试恢复v13并保持v15产物不变，生产未触发回退。[Issue250](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/250)不自动关闭。

完整本地操作记录：`/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/four-model-v15-publication-20260912/VERIFICATION.txt`；operation facts：`/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/four-model-v15-publication-20260912/deployment-operation-final.json`。

## 授权清理与文字澄清最终上线

用户明确授权后，在同一部署锁内重新核验 current、全部容器挂载和 symlink 引用，仅删除以下三个已审计 v11 目录（共同根目录 `/opt/llm-abm-marketing-sim-report/releases/`）：
- `full-pool-strict-formal-v11-production-20260819T153532Z`
- `full-pool-strict-formal-v11-production-paged-20260822T101000Z`
- `full-pool-strict-formal-v11-production-responsive-20260821T155000Z`

清理时间：2026-09-12T16:27:13.853319+00:00。可用空间从 458387456 增至 6315184128 bytes（约释放5.45GiB）。清理前后当前v15和受保护v13共309个文件bytes/mode完全一致，current未变；v12未删除。随后继续发布已验证的immutable候选，未改域名、主机、远程根目录或部署结构。

此前空间不足的上传失败（exit2）发生在原子切换前，保留于 `deploy-final-space-failure.log`；本次正式重试exit0，部署时间 `2026-09-12T16:41:27Z`（新加坡时间2026-09-13 00:41:27）。线上已切换至 `revised-four-model-v15-20260912T105000Z`；直接生产回退点是前一v15 `revised-four-model-v15-20260912T102200Z`，v13也保留。

本次相对前一v15只更新历史总说明的中英文正文、对应语言目录和release provenance/manifest；所有分析及13个新下载完全不变。

原中文：
> 以下 Primary-Shadow、Ranking Weight 与 Prompt-Model evidence 继续绑定原始 1,000-user denominator 和历史 direct-action 机制；它们不是当前 realized result。

现中文：
> 以下研究沿用原始 1,000-user sample，与 36,400-user 主实验分开。Primary-Shadow、排序权重与旧 GPT 析因保留历史 direct-action 机制；新增跨厂商四模型恢复研究独立使用 Judgment → Realization 两阶段机制，不合并不同 run 或分母。

英文同步：
> The studies below use the original 1,000-user sample, separately from the 36,400-user main experiment. Primary-Shadow, ranking-weight and historical GPT factorial evidence retain their direct-action mechanism. The added cross-provider four-model recovery study independently uses Judgment to Realization; different runs and denominators are not pooled.

具体澄清：1,000-user研究与36,400-user主实验分开；历史Primary-Shadow、排序权重、旧GPT析因保留direct-action；新增跨厂商四模型独立使用Judgment → Realization；不同run和分母不合并。没有改变结果、阈值、配对样本或结论。公网三个viewport及全部48个切换状态验收通过，另逐项对齐13下载、48图面板、16表行、2320行CSV。
