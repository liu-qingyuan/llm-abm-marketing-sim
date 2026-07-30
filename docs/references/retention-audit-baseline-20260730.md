# Retention Audit Dry Run

- schema: `retention-audit-v1`
- ready_for_cleanup: `false`
- aggregate_bytes: `6475441711`
- protected_bytes: `640291495`
- lineage_bytes: `5187512688`
- unknown_bytes: `242067362`
- protected_roots: `6`
- approved_candidates: `9`
- human_review_roots: `5`
- deferred_unknowns: `3`

## Protected Roots

- `configs/latent_attributes/jinjiang_user_latent_attributes_v1.yaml`
- `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-20260624T092200Z`
- `data/processed/jinjiang_douyin/jinjiang-final-caption-hashtag-comments-profiles-latent-v1-validation-20260705T000000Z`
- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z`
- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z`
- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z`

## Approved Candidates

Structured exact file actions: `5180`.

| candidate root | action | regular files | aggregate bytes |
|---|---|---:|---:|
| `.gitnexus` | `delete` | 20 | 6125569188 |
| `.mypy_cache` | `delete` | 4949 | 175567460 |
| `.pytest_cache` | `delete` | 6 | 74130 |
| `.ruff_cache` | `delete` | 136 | 236410 |
| `playwright-report` | `delete` | 1 | 529332 |
| `runs/issue-28-final-research-offline-v2` | `delete` | 9 | 3500115 |
| `runs/jinjiang-concurrent-message-mock-validation-20260726T202200Z` | `delete` | 23 | 83277240 |
| `runs/jinjiang-concurrent-message-mock-validation-20260726T203300Z` | `delete` | 23 | 83277240 |
| `test-results` | `delete` | 13 | 3410596 |

## Approved Directory Postconditions

Structured directory postconditions are recorded per exact directory in the structured result.
- `.gitnexus`: 8 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `.mypy_cache`: 247 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `.pytest_cache`: 3 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `.ruff_cache`: 5 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `playwright-report`: 1 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `runs/issue-28-final-research-offline-v2`: 1 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `runs/jinjiang-concurrent-message-mock-validation-20260726T202200Z`: 1 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `runs/jinjiang-concurrent-message-mock-validation-20260726T203300Z`: 1 directory postcondition(s); all recorded files and child directories must be processed before removal.
- `test-results`: 4 directory postcondition(s); all recorded files and child directories must be processed before removal.

## Human Review Roots

- `archive/jinjiang-historical-runs-20260623T022534Z`
- `data/raw/tikhub/douyin/jinjiang_hotel/jinjiang-profile-expansion-derived-20260622T151059Z-batch-full`
- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T012728Z`
- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T130742Z`
- `runs/jinjiang-field-lineage-mock-validation-20260720T105313Z`

## Deferred Unknowns

- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T012728Z`
- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T130742Z`
- `runs/jinjiang-field-lineage-mock-validation-20260720T105313Z`

## Violations

- none
