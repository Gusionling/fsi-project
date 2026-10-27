# 데이터 제작 진행 현황 (owner: data)

세션이 끊겨도 이어서 할 수 있게 단계별 상태를 적는다. 건수는 `python eval/v3/data/verify_counts.py`, 품질은 `python eval/v3/data/lint_data.py` 로 확인한다.

| 단계 | 산출물 | 상태 |
|---|---|---|
| 1 | topics.json (15개), registry/entities.json (계좌 10·URL 10·전화 7), registry/procedures.json (31개) | 완료 — 공격 데이터보다 먼저 커밋(`b6d8acd`) |
| 2 | 도구: data_lib, lint_data, verify_counts, 생성·조립·점검 스크립트 | 완료 |
| 3 | 정상 dev 230(짝 144 + 독립 86) / calib 200 / test_sealed 400 | 완료 |
| 4 | donors 540 (dev·calib 각 18 / topic) | 완료 |
| 5 | 공격 dev 276 (T1 30 · T2 100 · T3 40 · T4 106; 최소 250 + top-up-0 26), T4 B0/B1 시험 106/106 통과 | 완료 |
| 6 | 무결성 dev 60 | 완료 |
| 7 | 감사 30건(audit_sample.csv), data.md | 완료 |

## 남은 일 / 이어서 하려면
- harness 의 `executed_set --split dev` 결과에서 T2·T4·엔티티 없는 공격 중 E < 60 인 구분이 있으면 보충 라운드(top-up-1): `build_topup.py` 를 참고해 행을 추가하고 generator 에 `top-up-1` 을 적는다. verify 목표값은 바꾸지 않는다.
- 사용자: `V3_ALLOW_SEALED=1 python eval/v3/data/lint_data.py` 로 sealed 전체 lint 를 한 번 확인.
- 재조립: `python eval/v3/data/assemble.py` (raw/ + prompts/ 의 문구에서 cases_*.jsonl 을 다시 만든다).
