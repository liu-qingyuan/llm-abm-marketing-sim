# 四模型恢复稳健性分析 v15 发布记录

## 已实际发布与验收

- 公网：[Final Research](https://abm.q1ngyuan.top/)；release `revised-four-model-v15-20260912T102200Z`，部署时间 `2026-09-12T10:46:56Z`。
- Report/Analysis commit `a3c582cf538196ee993844f75e2fba231c59a8d3`；部署回读修复 `c02ca1a4fe930bd03ec6a95585e67df7fb280c1c`。
- Report SHA256 `621a252f2e9b5cf35a06a36cda8d7d4e3f1951fbded28284dddb0ed37aa22f63`；manifest SHA256 `342077aede7adac966088b5db3ec25ed385d8341784e7e459e3470030ad9ba25`。
- Contract SHA256 `b5eb95bd1668c16294a6c20d5a136722828413fe44694440f5a814e61ac22749`；immutable source `/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/revised-four-model-v15-ticket-250-20260912/revised-four-model-v15-20260912T102200Z`。
- 来源 `/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/01a08bb3-1446-7f51-8933-cd49b50e9ccb/four-model-final-20260912-verified`；Evidence SHA256 `a7407bf355d6049af8667a69b540fe2b29591d7f8e7ef71d6cb08d01fee72b17`；原plan SHA256 `2d64026ce755a5a5c3e8dd42f6c74add7dc1435b42adef3cbc47dac030da9b16`，source HEAD134884 / `a28681fbaf27c90552dd4a8c4e410696353e99ff18dc176d6ec5a41872311977`。
- [Analysis](https://abm.q1ngyuan.top/revised-robustness/analysis.json)、[Evidence](https://abm.q1ngyuan.top/revised-robustness/evidence.json)及13个新增下载同源；161个artifact可访问，63个完整body hash、98个大文件manifest绑定校验通过；三个viewport公网交互通过。
- 48图面板、16行cell表、2320行CSV与JSON逐项一致。146个旧证据文件bytes不变；主实验、Historical、Primary/Shadow、排序权重及旧GPT析因保留。

## 后续文字澄清候选：尚未发布

`revised-four-model-v15-20260912T105000Z` / commit `a747bb50fa0a4f597d97892797044fd932329b24` 仅澄清中英文历史总说明中旧direct-action与新增two-stage机制的边界；分析和13个新增下载bytes完全相同。候选contract SHA256 `16381a61677bce3ac09cd85053810fe66d909ce36155f0455b4d3c46a2be5bb9`，report SHA256 `085a572c55bc88f5a8956f87ac731802e6866a9e3c81456266757402147de44e`，目录 `/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/revised-four-model-v15-ticket-250-20260912/revised-four-model-v15-20260912T105000Z`。

Local正式preflight、120项相关回归及本地三viewport交互通过。远端上传以exit2停止（19G根分区98%占用、余447M，约1.7GiB候选放不下）；尚未运行该候选的health/cutover/public gates。其partial upload已清理，current仍为上方已验收v15，v13回退点保留。清理任何旧远端release前等待用户授权；没有删除旧release。

## 方法与限制

本次只完成28800/16cells/480barriers；原五模型36000/20/600不标完成，Gemini3.8FlashHigh为0调用。仅Batch0共享20seedusers×3messages配对，其余路径与交互描述性解释。Kimi33订阅k3-256k+7167官方kimi-k3；108失败、5archived unknown与历史token null保留。原交付eligibility=false不改写。

新增Provider calls=0。原source18files及weekly2files bytes/mode不变。120项相关回归通过；全量pytest未完成（既有慢速offline recovery integration中约20分钟后中止，exit143）。全仓Ruff42项为3个baseline文件的既有问题；pyright未安装；修改范围Ruff、编译、bash语法通过。

[Issue250](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/250)保持OPEN。详细证据：`/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/four-model-v15-publication-20260912/VERIFICATION.txt`；当前状态：`/Users/liuqingyuan/work/llm-abm-marketing-sim/outputs/four-model-v15-publication-20260912/publication-status.json`。
