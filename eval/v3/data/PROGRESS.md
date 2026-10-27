# 데이터 제작 진행 현황 (owner: data)

세션이 끊겨도 이어서 할 수 있게 단계별 상태를 적는다. 건수는 `python eval/v3/data/verify_counts.py` 로 확인한다.

| 단계 | 산출물 | 상태 |
|---|---|---|
| 1 | topics.json (15개), registry/entities.json, registry/procedures.json (31개) | 완료 — 공격 데이터보다 먼저 커밋 |
| 2 | 도구(verify_counts, lint_data, 생성 스크립트) | 대기 |
| 3 | 정상 dev 200 / calib 200 / test_sealed 400 | 대기 |
| 4 | donors (dev·calib 각 ≥15 / topic) | 대기 |
| 5 | 공격 dev 250 (T1 30 · T2 90 · T3 40 · T4 90) | 대기 |
| 6 | 무결성 dev 60 | 대기 |
| 7 | audit_sample.csv, data.md | 대기 |
