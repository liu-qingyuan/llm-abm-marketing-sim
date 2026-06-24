# 锦江酒店 Douyin 用户 Profile 扩展验证小结

- source dataset: `data/processed/jinjiang_douyin/jinjiang-caption-hashtag-comments-excluding-binguan-adding-jian-derived-20260621T025127Z`
- target users: 36400
- sec_uid evidence recovery coverage: 36400 / 36400
- attempted profiles: 36400
- successful profiles: 36215
- failed profiles: 185
- missing sec_uid users: 0
- profiles_collected: True
- partial: False
- partial_reason: 
- expansion_state: live_profile_complete
- profile_api: requested `handler`, resolved `handler`
- quota_stopped_profiles: 0
- current_run_success_delta: 26936
- cost_guard_triggered: False
- recommended_resume_mode: handler
- quota/rate limit: see partial_reason and endpoint_call_counts
- secrets read/printed/written: no
- raw/processed large data committed: no

## 成本审计（聚合）

| 指标 | 值 |
|---|---:|
| quota_stopped_profiles | 0 |
| current_run_success_delta | 26936 |

### endpoint_call_counts

| endpoint | calls |
|---|---:|
| handler_user_profile | 27121 |

### http_status_counts

| status/category | rows |
|---|---:|
| 400 | 6 |
| 502 | 136 |
| identity_mismatch_or_empty_response | 9 |
| provider_error | 34 |

## 字段覆盖率

| 字段 | 非空行数 |
|---|---:|
| bio | 22126 |
| follower_count | 26902 |
| following_count | 26812 |
| nickname | 36215 |
| sec_user_id | 36400 |
| user_id | 36400 |
| verified_type | 222 |
| video_count | 21336 |

说明：本文档只展示聚合统计，不展开昵称、bio、signature 等用户明细。`brand_attitude` 与分享倾向等字段当前为后续模型默认/派生字段，不视为真实观测行为。
