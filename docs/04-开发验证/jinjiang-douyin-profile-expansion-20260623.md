# 锦江酒店 Douyin 用户 Profile 扩展验证小结

- source dataset: `data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z`
- target users: 36400
- sec_uid evidence recovery coverage: 36400 / 36400
- attempted profiles: 9280
- successful profiles: 9279
- failed profiles: 1
- missing sec_uid users: 0
- profiles_collected: True
- partial: True
- partial_reason: quota_or_rate_limit
- expansion_state: live_profile_partial
- profile_api after guard: default `cost-safe` resolves to `handler_user_profile`; batch is explicit opt-in only
- cost_guard: profile HTTP 400/402/429 are not retried by default; batch HTTP 402/429 stops immediately; batch HTTP 400 defaults to handler downgrade
- recommended_resume_mode: `handler`
- current_run_success_delta field: added to future reports for aggregate-only cost audit
- quota/rate limit: see partial_reason and endpoint_call_counts
- secrets read/printed/written: no
- raw/processed large data committed: no

## 2026-06-23 充值后续跑状态

充值后已继续按同一 run `--resume` 抓取，live profile 成功数从 5,449 增至 9,279；当前最新停止原因是 TikHub profile endpoint 返回 HTTP 402 余额/付费额度不足，因此仍为真实 partial，未伪称全量完成。后续余额恢复后继续使用同一 run resume 命令即可跳过已成功用户并从剩余用户继续。

## 2026-06-23 成本保护补丁

为避免下一次充值后继续被 batch 失败批次消耗额度，profile CLI 已改为成本安全策略：默认 `--profile-api cost-safe`，即使用单用户 `handler_user_profile`；`--profile-api batch` 必须显式传入。错误契约改为结构化聚合审计：HTTP 400 视作 provider bad request/transient，不标记为 quota；HTTP 402/429 立即停止；报告新增 `http_status_counts`、`rejected_by_endpoint_status`、`current_run_success_delta`、`cost_guard_triggered`、`recommended_resume_mode` 和 `next_resume_command`。本文档仍只展示聚合统计，不展示用户昵称、bio、signature 或 raw payload。

## 字段覆盖率

| 字段 | 非空行数 |
|---|---:|
| bio | 6658 |
| follower_count | 760 |
| following_count | 761 |
| nickname | 9279 |
| sec_user_id | 36400 |
| user_id | 36400 |
| verified_type | 67 |
| video_count | 622 |

说明：本文档只展示聚合统计，不展开昵称、bio、signature 等用户明细。`brand_attitude` 与分享倾向等字段当前为后续模型默认/派生字段，不视为真实观测行为。
