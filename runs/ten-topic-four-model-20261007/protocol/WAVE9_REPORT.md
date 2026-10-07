# 第九阶段：遵守Retry-After及中断恢复

Gemini三个条件收到实际HTTP503以及约7192秒Retry-After。此前本轮runner忽略wait_seconds，产生14次在已知冷却期限前的物理请求。这是本轮调度问题，已最小修复：在后续intent/dispatch之前等待观测期限；独立账本验收对新策略拒绝提前调用，对旧14次明确保留，不修改或删除原账本。原失败和unknown均保留，不填入判断。这些失败没有被接纳为正式决策，影响调用数量/等待，不改变已落地的真实判断。

上一轮被显式中断后，实查所有原PID和七个tool handles均缺失；不是凭观察超时重启。三条Kimi已有intent但无response，单独追加unknown分类。六个最新journal仅追加终止标记，原bytes保持prefix，详情见INTERRUPTION_RECOVERY.json。重新查询官方余额HTTP200，可用余额¥141.2448；只读账户请求不计模型判断。Kimi三个条件恢复实际曝光补采；Gemini三个进程已执行到同一缺口并等待2026-10-07 06:13 UTC（新加坡14:13）后显式新批次，不切换通道/模型。所有新增请求仍计入29,143次上限，现金授权无限；实际现金费用未知，不由余额差额推定。

64项相关离线回归测试通过，Ruff F与py_compile通过。deadline算法单测及独立账本时间验收不共用实现；metadata-only测试没有合成正式判断。真实采集另记账，验收/分类/测试Provider调用为0。原抽样锚点、样本、排序、30批屏障及生成设定不变。

当前十个正式条件完成，完整16条件、28,800曝光验收尚待运行结束。论文/canonical未修改或部署，旧结果不覆盖，goal保持active。全仓库慢扫描与缺失pyright不重复，适用测试覆盖范围仍限本轮运行接缝；不会据此声称全仓库无问题。精确baseline/modified/rollback命令/结果见VERIFICATION_WAVE9.txt；rollback仅作用scratch，生产修改保留。
