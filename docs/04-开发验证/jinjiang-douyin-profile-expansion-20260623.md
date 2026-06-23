# 锦江酒店 Douyin 用户 Profile 扩展验证小结

- source dataset: `data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z`
- target users: 36400
- sec_uid evidence recovery coverage: 36400 / 36400
- attempted profiles: 5450
- successful profiles: 5449
- failed profiles: 1
- missing sec_uid users: 0
- profiles_collected: True
- partial: True
- partial_reason: quota_or_rate_limit
- expansion_state: live_profile_partial
- quota/rate limit: see partial_reason and endpoint_call_counts
- secrets read/printed/written: no
- raw/processed large data committed: no

## 字段覆盖率

| 字段 | 非空行数 |
|---|---:|
| bio | 4138 |
| follower_count | 705 |
| following_count | 706 |
| nickname | 5449 |
| sec_user_id | 36400 |
| user_id | 36400 |
| verified_type | 38 |
| video_count | 581 |

说明：本文档只展示聚合统计，不展开昵称、bio、signature 等用户明细。`brand_attitude` 与分享倾向等字段当前为后续模型默认/派生字段，不视为真实观测行为。

## 2026-06-23 续跑说明

本轮已按最终 corrected dataset 继续重试 profile 抓取，并保持 `--resume` checkpoint：

- 批量接口 `fetch_batch_user_profile_v2` 曾继续增加成功数，但随后返回 HTTP 402；
- 单用户接口 `handler_user_profile` smoke 成功 5/5，随后全量续跑继续增加成功数；
- 最终单用户接口也返回 HTTP 402，错误语义为余额/免费额度不足，因此停止继续消耗请求；
- 当前不是 36,400/36,400 全量完成，而是真实 partial：live profile 成功 5,449，仍有 30,950 个目标用户未完成 live profile 抓取；
- 本地 raw 错误记录已做 header/token 脱敏清洗，Markdown 仍只保留聚合统计。

后续若 TikHub 付费余额/额度恢复，可继续执行同一个 resume 命令，脚本会跳过已成功用户并从剩余 quota_stopped/pending 用户继续。
