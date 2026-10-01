# 체크포인트 2 — dev set(파일럿 142건) 임계값 결정 결과

> `docs/decision_protocol.md`의 임계값 규칙(3번 항목)을 적용한 결과다. 통과/실패 판단이나
> "어느 방법이 낫다"는 해석은 담지 않는다 — 숫자만 기록한다. 홀드아웃 평가(체크포인트 3)가
> 끝나기 전에는 여기 적힌 임계값과 구현을 바꾸지 않는다(`git tag protocol-frozen-v1` 참고).

- 실행 일시: 2026-10-01 (dev set 로더: `eval/decision_experiment/common.py::load_dev_set`)
- 실제 API 호출: B1 142회 + B2 142회 = 284회(`gpt-4o-mini`). B0/B3는 로컬 계산(API 호출 없음).
  M0는 `logs/pilot_real_run_20260929T064111Z.json`에 이미 기록된 실행 결과를 캐시로 재계산
  (새 API 호출 없음).
- 원본 결과(청크별 점수·응답 전체): `logs/checkpoint2_dev_run_20261001T100224Z.json`
  (`.gitignore` 대상, 커밋하지 않음)
- dev 모집단: 정상 90건(easy + hard negative 15 + 파일럿2), 인젝션 52건(naive 32 + optimized 20)

## 연속/준연속 점수 방법

| 방법 | 선택된 임계값 | dev FPR | dev recall | recall Wilson 95% CI | AUC |
|---|---|---|---|---|---|
| M0 | 0.25 | 0.044 | 0.519 | [0.387, 0.649] | 0.743 |
| B0 (어휘 기준선, 0~5점) | 2 | 0.000 | 0.846 | [0.725, 0.920] | 0.987 |
| B1 (LLM 단일 판정, risk_score 0~100) | 70 | 0.044 | 0.904 | [0.794, 0.958] | 0.941 |

## 이진 방법

| 방법 | dev FPR | 규칙 상태 | dev recall | recall Wilson 95% CI |
|---|---|---|---|---|
| B2 (KAD, 청크별 카나리 토큰) | 0.000 | 규칙 충족(FPR≤5%) | 0.000 | [0.000, 0.069] |
| B3 (정적 엔티티 화이트리스트) | 0.000 | 규칙 충족(FPR≤5%) | 0.423 | [0.299, 0.558] |

## 동결된 구현 파일의 SHA-256 해시 (`protocol-frozen-v1` 태그 시점)

| 파일 | SHA-256 |
|---|---|
| `docs/decision_protocol.md` | `4ba54061d5a186f464b1223e6193fb5b736946b659cfa3df02bf11ac386a20ca` |
| `eval/decision_experiment/common.py` | `04b1054b83ee7feba32ad07bc0a1064500152da2cd9d923fefb6788104c7ed3c` |
| `eval/decision_experiment/m0_scoring.py` | `7df1c93ecf590ec6281128249110c38d94ca914f60f486d92e68d326730cc2f8` |
| `eval/decision_experiment/b0_lexical.py` | `adf878b03ee7b4ba3879280c83ab3a01b7253733133c1da7e0ca5ed343173e5b` |
| `eval/decision_experiment/b1_llm_judge.py` | `0610808d35ccdcf235f170b9be0b7b69edf224e41619e1a4fec2d68b23742ca5` |
| `eval/decision_experiment/b2_kad.py` | `2cedea9c754734cce4f124c4686d7609951bda6c0603c14859167a7304e23fc4` |
| `eval/decision_experiment/b3_whitelist.py` | `c116d5dba1cadbf806d3b2f2bcd025d672cb2a54dffa90548993a97f17eb7029` |
| `eval/decision_experiment/run_checkpoint2.py` | `5a97abf4cbbfa65163b745ef5ca34cff7bcaa36fdca6320a23fdcab7e42fb1cf` |

홀드아웃 실행(체크포인트 3) 전에 이 표의 해시값과 실제 파일의 해시가 다르면, 동결 이후 코드가
바뀐 것이다(`shasum -a 256 <파일>`로 재확인 가능).

## 참고 (판단 아님, 관찰 기록)

- B2의 dev recall이 0인 것은 dev set의 naive/optimized 공격이 B2를 피하도록 설계되지
  않았기 때문이다(그 역할은 홀드아웃 T4의 `b2_evasion` 그룹이 한다). 실제 응답 예시는
  보고 메시지에 별도로 첨부했다.
- M0는 이 dev set(파일럿 1~3)의 실제 실행 결과를 이미 보고 정규화 재군집으로 손을 본 상태로
  이 비교에 들어간다 — `docs/decision_protocol.md` 3번 항목의 "M0-베이스라인 비대칭 공지" 그대로
  적용된다. B0/B1/B2/B3는 dev 실행 전까지 이 데이터에 맞춰 조정된 적이 없다.
