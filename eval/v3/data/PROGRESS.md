# 데이터 제작 진행 현황 (owner: data)

세션이 끊겨도 이어서 할 수 있게 단계별 상태를 적는다. 건수는 `python eval/v3/data/verify_counts.py` 로 확인한다.

| 단계 | 산출물 | 상태 |
|---|---|---|
| 1 | topics.json (15개), registry/entities.json, registry/procedures.json (31개) | 완료 — 공격 데이터보다 먼저 커밋 |
| 2 | 도구: data_lib, lint_data, verify_counts, 생성(gen_*, assemble*), t4_probe | 완료 |
| 3 | 정상 dev 200(짝 134 + 독립 66) / calib 200 / test_sealed 400 | 완료 (assemble.py) |
| 4 | donors 540 (dev·calib 각 18 / topic) | 완료 |
| 5 | 공격 dev 276 (T1 30 · T2 100 · T3 40 · T4 106; 최소치 250 + top-up-0 26), T4 B0/B1 시험, 챗봇 실행 비율 사전 점검 | 완료 — rev1(질문·문서 정합) 적용 |
| 6 | 무결성 dev 60 | 완료 |
| 7 | 챗봇 실행 비율 사전 점검, audit_sample.csv, data.md | 진행 중 |
