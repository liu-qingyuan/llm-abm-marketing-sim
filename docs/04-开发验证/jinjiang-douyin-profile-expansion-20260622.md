# 锦江酒店 Douyin 用户 Profile 扩展验证小结

- source dataset: `data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z`
- target users: 36400
- attempted profiles: 0
- successful profiles: 0
- failed profiles: 0
- missing sec_uid users: 36400
- profiles_collected: False
- partial: True
- partial_reason: no_confirmed_sec_uid
- expansion_state: derived_only_no_confirmed_sec_uid
- quota/rate limit: see partial_reason and endpoint_call_counts
- secrets read/printed/written: no
- raw/processed large data committed: no

## 字段覆盖率

| 字段 | 非空行数 |
|---|---:|
| bio | 0 |
| follower_count | 0 |
| following_count | 0 |
| nickname | 0 |
| sec_user_id | 0 |
| user_id | 36400 |
| verified_type | 0 |
| video_count | 0 |

说明：本文档只展示聚合统计，不展开昵称、bio、signature 等用户明细。`brand_attitude` 与分享倾向等字段当前为后续模型默认/派生字段，不视为真实观测行为。
