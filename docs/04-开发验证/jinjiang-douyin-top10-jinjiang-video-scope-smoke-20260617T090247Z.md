# 锦江 Douyin top10 名称带锦江视频集合统计报告

- run: `jinjiang-top10-jinjiang-only-video-metadata-smoke-20260617T090247Z`
- scope: 只统计 10 个名称带 `锦江` 的 source challenge 与 caption hashtag。
- caption hashtag 口径: 只认显式 `#锦江...`；普通文本不进入主计数。
- comments/replies/profiles: 本阶段不抓取。

## A. Scope

1. 锦江都城酒店
2. 锦江之星酒店
3. 锦江酒店
4. 锦江之星
5. 锦江宾馆
6. 绵阳锦江国际酒店
7. 锦江之星品尚
8. 锦江酒店华西区
9. 锦江之星海口
10. 锦江酒店中国区

### Excluded

- `酒店`: 泛化酒店主题，且名称不带锦江
- `住宿`: 泛化/弱相关住宿主题，且名称不带锦江
- `高性价比酒店推荐`: 消费决策相关但名称不带锦江，不属于本轮名称带锦江 top10

## B. Source challenge 统计

| source_challenge_name | source_challenge_id | indexed_video_ids | selected_video_ids | videos_with_caption | videos_with_hashtags |
| --- | --- | --- | --- | --- | --- |
| 绵阳锦江国际酒店 | 7492373353357903924 | 10 | 10 | 10 | 10 |
| 锦江之星 | 1600871309340680 | 10 | 10 | 10 | 10 |
| 锦江之星品尚 | 1632849322176525 | 10 | 10 | 10 | 10 |
| 锦江之星海口 | 7642718226014537769 | 10 | 10 | 10 | 10 |
| 锦江之星酒店 | 1624819436442636 | 10 | 10 | 10 | 10 |
| 锦江宾馆 | 1608015311015939 | 9 | 9 | 9 | 9 |
| 锦江都城酒店 | 1629766950492163 | 10 | 10 | 10 | 10 |
| 锦江酒店 | 1614016211862532 | 10 | 10 | 10 | 10 |
| 锦江酒店中国区 | 1669845857481741 | 9 | 9 | 9 | 9 |
| 锦江酒店华西区 | 7474793640091453503 | 10 | 10 | 10 | 10 |

## C. Caption hashtag 统计

| caption_hashtag | matched_video_count | unique_video_count |
| --- | --- | --- |
| #锦江都城酒店 | 10 | 10 |
| #锦江之星酒店 | 10 | 10 |
| #锦江酒店 | 14 | 14 |
| #锦江之星 | 10 | 10 |
| #锦江宾馆 | 9 | 9 |
| #绵阳锦江国际酒店 | 10 | 10 |
| #锦江之星品尚 | 8 | 8 |
| #锦江酒店华西区 | 9 | 9 |
| #锦江之星海口 | 10 | 10 |
| #锦江酒店中国区 | 10 | 10 |

## D. Source vs caption 差异

- deduped_video_total: `98`
- multilabel_match_total: `100`
- source_without_matching_caption_hashtag: `7`
- caption_hashtag_source_mismatch: `9`
- videos_with_multiple_top10_caption_hashtags: `9`

## E. 评论数过千判断（metadata-only）

本阶段不抓评论。`metadata_comment_count >= 1000` 先标记为 metadata 层面过千；缺失或 challenge-page provenance 需要后续 detail/comment 阶段确认。

| video_id | source_challenge_name | caption_hashtags | metadata_comment_count | over_1000_by_metadata | comment_count_confidence | needs_comment_fetch |
| --- | --- | --- | --- | --- | --- | --- |
| 7357284521512881423 | 锦江之星品尚 | #锦江之星品尚 | 3 | false | metadata_level_needs_confirmation | true |
| 7532462167050063161 | 锦江之星品尚 | #锦江之星品尚 | 2 | false | metadata_level_needs_confirmation | true |
| 7537617115547209019 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 29 | false | metadata_level_needs_confirmation | true |
| 7538018441694530868 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 24 | false | metadata_level_needs_confirmation | true |
| 7538294225449209130 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 17 | false | metadata_level_needs_confirmation | true |
| 7544617256270253346 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 8 | false | metadata_level_needs_confirmation | true |
| 7564685669660069171 | 锦江之星品尚 | #锦江之星品尚 | 1 | false | metadata_level_needs_confirmation | true |
| 7567651107586379027 | 锦江之星品尚 | #锦江之星品尚 | 0 | false | metadata_level_needs_confirmation | true |
| 7571134422797033593 | 锦江之星品尚 | #锦江之星品尚 | 0 | false | metadata_level_needs_confirmation | true |
| 7602628711800420323 | 锦江酒店中国区 | #锦江酒店中国区 | 43 | false | metadata_level_needs_confirmation | true |
| 7604364045105302793 | 锦江酒店中国区 | #锦江酒店;#锦江酒店中国区 | 0 | false | metadata_level_needs_confirmation | true |
| 7619238058441596793 | 锦江宾馆 | #锦江宾馆 | 200 | false | metadata_level_needs_confirmation | true |
| 7619241684417669499 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7619632098429923450 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7619909289030073006 | 锦江都城酒店 | #锦江都城酒店 | 117 | false | metadata_level_needs_confirmation | true |
| 7620002987439868281 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7620646578278654821 | 锦江酒店中国区 | #锦江酒店中国区 | 8 | false | metadata_level_needs_confirmation | true |
| 7620690099411566278 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7621467975295481418 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7621567917785065957 | 锦江酒店中国区 | #锦江酒店;#锦江酒店中国区 | 2 | false | metadata_level_needs_confirmation | true |
| 7621812978183428602 | 锦江之星酒店 | #锦江之星酒店 | 2 | false | metadata_level_needs_confirmation | true |
| 7622498001190535089 | 锦江都城酒店 | #锦江都城酒店 | 14 | false | metadata_level_needs_confirmation | true |
| 7622624783087324326 | 锦江都城酒店 | #锦江都城酒店 | 27 | false | metadata_level_needs_confirmation | true |
| 7623680661521847795 | 锦江都城酒店 | #锦江都城酒店 | 26 | false | metadata_level_needs_confirmation | true |
| 7624084876211358985 | 锦江宾馆 | #锦江宾馆 | 12 | false | metadata_level_needs_confirmation | true |
| 7624486835444661702 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7624487086679355877 | 锦江都城酒店 | #锦江都城酒店 | 11 | false | metadata_level_needs_confirmation | true |
| 7624709327441431823 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7624790515451868581 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7626985678442574577 | 锦江之星酒店 | #锦江之星酒店;#锦江之星 | 3 | false | metadata_level_needs_confirmation | true |
| 7627021857354435890 | 锦江之星酒店 | #锦江之星酒店 | 9 | false | metadata_level_needs_confirmation | true |
| 7627489663091757553 | 锦江酒店中国区 | #锦江酒店中国区 | 0 | false | metadata_level_needs_confirmation | true |
| 7627676410090464697 | 锦江之星品尚 | #锦江之星;#锦江之星品尚 | 0 | false | metadata_level_needs_confirmation | true |
| 7627864726677203962 | 锦江酒店 | #锦江酒店 | 425 | false | metadata_level_needs_confirmation | true |
| 7628828833948503347 | 锦江都城酒店 | #锦江都城酒店 | 20 | false | metadata_level_needs_confirmation | true |
| 7628906999341864802 | 锦江酒店中国区 | #锦江酒店;#锦江酒店中国区 | 195 | false | metadata_level_needs_confirmation | true |
| 7631949039454139747 | 锦江之星酒店 | #锦江之星酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7633022371629460389 | 锦江之星酒店 | #锦江之星酒店 | 28 | false | metadata_level_needs_confirmation | true |
| 7633748436747160851 | 锦江都城酒店 | #锦江都城酒店;#锦江酒店 | 35 | false | metadata_level_needs_confirmation | true |
| 7635703937248636081 | 锦江之星品尚 |  | 0 | false | metadata_level_needs_confirmation | true |
| 7638529923942671269 | 锦江宾馆 | #锦江宾馆 | 14 | false | metadata_level_needs_confirmation | true |
| 7639258959762168682 | 锦江酒店华西区 |  | 0 | false | metadata_level_needs_confirmation | true |
| 7639622376216936639 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7640041124777790746 | 锦江宾馆 | #锦江宾馆 | 6 | false | metadata_level_needs_confirmation | true |
| 7640712765140763529 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 19 | false | metadata_level_needs_confirmation | true |
| 7641509515775006315 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7642295202757712357 | 锦江酒店 | #锦江酒店;#锦江酒店中国区 | 82 | false | metadata_level_needs_confirmation | true |
| 7642352042170683310 | 锦江酒店中国区 | #锦江酒店中国区 | 14 | false | metadata_level_needs_confirmation | true |
| 7642366144544051663 | 锦江酒店 |  | 5 | false | metadata_level_needs_confirmation | true |
| 7642688603060345189 | 锦江之星 | #锦江之星 | 1 | false | metadata_level_needs_confirmation | true |
| 7642720681508126949 | 锦江之星酒店 | #锦江之星酒店 | 6 | false | metadata_level_needs_confirmation | true |
| 7642918373168975592 | 锦江之星 | #锦江之星 | 3 | false | metadata_level_needs_confirmation | true |
| 7643305067735061115 | 锦江之星 | #锦江之星 | 5 | false | metadata_level_needs_confirmation | true |
| 7643691628460442266 | 锦江都城酒店 | #锦江都城酒店 | 1 | false | metadata_level_needs_confirmation | true |
| 7644207770070609478 | 绵阳锦江国际酒店 | #绵阳锦江国际酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7645231696577229311 | 锦江都城酒店 | #锦江都城酒店 | 7 | false | metadata_level_needs_confirmation | true |
| 7645934762439716273 | 锦江之星海口 | #锦江之星海口 | 7 | false | metadata_level_needs_confirmation | true |
| 7645934793426999759 | 锦江之星海口 | #锦江之星海口 | 2 | false | metadata_level_needs_confirmation | true |
| 7645935079253253619 | 锦江之星海口 | #锦江之星海口 | 2 | false | metadata_level_needs_confirmation | true |
| 7645937585018660337 | 锦江之星海口 | #锦江之星海口 | 1 | false | metadata_level_needs_confirmation | true |
| 7645937683982488059 | 锦江之星海口 | #锦江之星海口 | 5 | false | metadata_level_needs_confirmation | true |
| 7645942368823305061 | 锦江之星海口 | #锦江之星海口 | 0 | false | metadata_level_needs_confirmation | true |
| 7645943867984507209 | 锦江之星海口 | #锦江之星海口 | 2 | false | metadata_level_needs_confirmation | true |
| 7645945093715527525 | 锦江之星海口 | #锦江之星海口 | 4 | false | metadata_level_needs_confirmation | true |
| 7646063194931007651 | 锦江之星海口 | #锦江之星海口 | 1 | false | metadata_level_needs_confirmation | true |
| 7646413649577841906 | 锦江之星海口 | #锦江之星海口 | 1 | false | metadata_level_needs_confirmation | true |
| 7646689660202623089 | 锦江之星酒店 | #锦江之星酒店 | 7 | false | metadata_level_needs_confirmation | true |
| 7648139957123452134 | 锦江酒店 | #锦江酒店 | 1 | false | metadata_level_needs_confirmation | true |
| 7648522954431638898 | 锦江酒店华西区 | #锦江酒店华西区 | 1 | false | metadata_level_needs_confirmation | true |
| 7648565455925305590 | 锦江之星酒店 | #锦江之星酒店 | 3 | false | metadata_level_needs_confirmation | true |
| 7649179315309561522 | 锦江之星 | #锦江之星 | 1 | false | metadata_level_needs_confirmation | true |
| 7649308858476793097 | 锦江宾馆 | #锦江宾馆 | 2 | false | metadata_level_needs_confirmation | true |
| 7650058068524703985 | 锦江之星 | #锦江之星 | 12 | false | metadata_level_needs_confirmation | true |
| 7650480602995717609 | 锦江酒店中国区 | #锦江酒店中国区 | 393 | false | metadata_level_needs_confirmation | true |
| 7650768238049330161 | 锦江酒店 | #锦江酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7650778960914191028 | 锦江之星 | #锦江之星 | 2 | false | metadata_level_needs_confirmation | true |
| 7651207889817890803 | 锦江酒店 | #锦江酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7651538641722322790 | 锦江之星品尚 | #锦江之星品尚 | 0 | false | metadata_level_needs_confirmation | true |
| 7651580606035469668 | 锦江之星 |  | 1 | false | metadata_level_needs_confirmation | true |
| 7651617559514506737 | 锦江之星 |  | 0 | false | metadata_level_needs_confirmation | true |
| 7651619845352254885 | 锦江之星 |  | 0 | false | metadata_level_needs_confirmation | true |
| 7651706654878485925 | 锦江宾馆 | #锦江宾馆 | 0 | false | metadata_level_needs_confirmation | true |
| 7651820406185952938 | 锦江之星 | #锦江之星 | 11 | false | metadata_level_needs_confirmation | true |
| 7651838663278283365 | 锦江酒店 | #锦江酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7651856123640827170 | 锦江宾馆 | #锦江宾馆 | 10 | false | metadata_level_needs_confirmation | true |
| 7651860525504472411 | 锦江宾馆 | #锦江宾馆 | 4 | false | metadata_level_needs_confirmation | true |
| 7651881763723924651 | 锦江之星品尚 | #锦江之星;#锦江之星品尚 | 0 | false | metadata_level_needs_confirmation | true |
| 7651883470444371042 | 锦江酒店 | #锦江酒店 | 2 | false | metadata_level_needs_confirmation | true |
| 7651958264884634996 | 锦江酒店 | #锦江酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7651977534540207594 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7651995085157061809 | 锦江宾馆 | #锦江宾馆 | 4 | false | metadata_level_needs_confirmation | true |
| 7652128945068305329 | 锦江之星品尚 |  | 0 | false | metadata_level_needs_confirmation | true |
| 7652175287262233829 | 锦江酒店 | #锦江酒店 | 3 | false | metadata_level_needs_confirmation | true |
| 7652180789711641202 | 锦江都城酒店 | #锦江都城酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7652186514637649896 | 锦江之星酒店 | #锦江之星酒店 | 46 | false | metadata_level_needs_confirmation | true |
| 7652192906987513201 | 锦江酒店华西区 | #锦江酒店华西区 | 0 | false | metadata_level_needs_confirmation | true |
| 7652199374404058555 | 锦江之星酒店 | #锦江之星酒店 | 0 | false | metadata_level_needs_confirmation | true |
| 7652249669011440996 | 锦江酒店中国区 | #锦江酒店;#锦江酒店中国区 | 0 | false | metadata_level_needs_confirmation | true |

## Safety audit

- comments_collected: `False`
- profiles_collected: `False`
- forbidden_endpoint_calls: `{}`
