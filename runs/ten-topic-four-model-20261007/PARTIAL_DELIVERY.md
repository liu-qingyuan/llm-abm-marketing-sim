# 十话题四模型：保留的部分交付及阻断证据

状态：待恢复，10/16正式条件完成并独立验收；不是完整四模型研究，暂不作完整论文结果或正式发布使用。

Worktree: /Users/liuqingyuan/.codex/worktrees/ten-topic-offline-replay/llm-abm-marketing-sim
分支: codex/ten-topic-full-pool-replay
起点HEAD: 7bfafab09ba0f5d6bda9812ab1f415e948e9a5ae

完成条件：GPT P0–P3、DeepSeek V4.1 Flash P0–P3、Kimi P0、Gemini P0。18,000曝光、300批次屏障，实际曝光判断库18,000唯一输入，不声称完整48,000候选库。

未完成：Kimi P1/P2/P3及Gemini P1/P2/P3。Kimi余额只读复查仍available0、cash -0.0797 CNY；P1原420曝光与quota429拒绝保留。Gemini每模板一条输入已触及原3尝试，HTTP503持续；请求另建显式补采批次权限已发出，尚未收到回答。P2/P3的新执行均已终止，不假称任务还在运行。当前存活study/queue为0；controller和finisher均已明确partial终态。

程序及适用检查：30 focused offline tests通过；全src/tests/scripts py_compile通过；全相关Ruff42问题与原项目code/path/行列/message完全一致，新增0；pyright环境缺失127，未安装新依赖；完整pytest未盲重跑（此前已定位80分钟historical recovery扫描）。新增quota元数据恢复4单元测试通过，不发模型或账户HTTP请求。

本轮最新阻断复查只有官方余额metadata GET1，模型Provider调用0；生产历史调用另见ledger-audit/LEDGER_AUDIT.json。账户可用余额不是本研究实际消耗，实际现金费用仍未知，不写零。

恢复要求：官方Kimi补足余额；Gemini原网关恢复正常，并确认原三尝试用尽后是否另开显式补采批次。模型、渠道、P0–P3、完整输入、抽样锚点、seed20260823及全局29,143物理上限保持。失败/unknown不删除，不以模拟输出补结果。

结果路径：progress-report/conditions.csv、messages.csv、segments-messages.csv、curves.csv、old-new.csv、direct-seed-panel.csv；independent-acceptance/ACCEPTANCE_PROGRESS.json；bank-progress/manifest.json；ledger-audit/LEDGER_AUDIT.json。皆为部分成果，正式16条件交付仍待完成。原源目录、前阶段全样本和两项GPT敏感性结果保留，论文/canonical未改或部署。
