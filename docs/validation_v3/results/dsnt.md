# DSNT Phase A 보고서

## 1. 요약

진단용 donor 교체·뼈대 거리·split conformal·CSV 진단을 구현했다.
스텁 기반 검증만 수행했다. 효과/폐기 기준 판정은 아직 하지 않았다.
제안자는 Claude이며 구현자는 제안을 유리하게 튜닝하지 않았다.

## 2. 실행 환경과 프리플라이트 결과

Python 3.12.14, 오프라인 FakeLLM 모드. 실제 모델 사용 없음.
RunContext의 기본 모델 이름은 gpt-4o-mini이며 실제 호출했다는 의미가 아니다.
R10 (a) OPENAI_API_KEY의 존재만 확인(값 미열람).
(b) API 도달 및 (c) 실제 임베딩 프리플라이트는 수행하지 못함:
이 Phase A 체크아웃에는 실제 RunContext.llm 클라이언트가 없고 common 구현은 범위 밖이다.
R6을 우회하는 직접 SDK 클라이언트를 만들지 않았다. 온라인 준비를 주장하지 않으며
실제 LLM/임베딩 실험과 Phase B는 시작하지 않았다.

## 3. 무엇을 만들었나

모두 `eval/v3/candidates/dsnt/` 아래:

- defense.py: DSNTDefense, gate 조합·calib 정상 보정·결정성 설정 검사
- skeleton.py: 우선순위 기반 값 마스킹
- distance.py: 토큰 편집거리·ctx.llm 임베딩 cosine
- conformal.py: p값·최소 p값·불충분 표본 경고
- diagnostic.py: 실제 실행 행+Case → score_distribution.csv / diagnostic.json
- design.md / README.md: 불변 조건·선택·약점·사용법

`tests/v3/dsnt/`: owner 전용 stubs와 마스킹·거리·보정·게이트·진단 테스트.
테스트 실행 기록: `eval/v3/results/dsnt/phase_a_pytest.txt`.
그 안의 테스트 수는 단위 테스트 실행 수이며 연구 성능 수치가 아니다.

## 4. 설계 결정

| 결정 | 이유 | 대안 |
|---|---|---|
| 다중 target 동시 교체, target별 seed 변형 | 공격 target이 재실행에 남지 않게 함 | 개별 교체는 별도 집계 필요 |
| fit은 정상 전체의 raw s, run은 gate 이후 s | gate로 calib 정상 분포를 선택하지 않음 | gate 통과 정상만 조건부 보정 |
| 최소 p>α면 경고·판정 보류 | 불가능한 차단을 가능하다고 보이지 않음 | α를 자동 변경하지 않음 |
| p≤α, α 감소는 차단 감소 | 정해진 conformal 방향 보존 | 고위험에서 α 감소라는 잘못된 해석 배제 |
| 값만 바뀐 공격의 맹점을 테스트로 고정 | V4 기여와 DSNT 진단을 혼동하지 않음 | 공격에 맞춘 마스킹 수정 안 함 |
| 진단 시 미채점 누락 개수 공개 | gate 차단을 점수 0으로 위조하지 않음 | 전체 성능은 하네스에서 별도 측정 |

추가 근거·대안은 후보 design.md의 설계 결정 표에 있다.

## 5. 결과 표

Phase B 에서 채움. 연구 실행 산출물 없음. author_model별·신뢰구간 결과도 미측정.
단위 테스트의 합성 fixture는 실제 성능 측정에 사용하지 않았다.

## 6. 폐기 기준 판정

Phase B 에서 채움. PREREG 미확정, G1/G2/G3 확인 전이므로 판정하지 않는다.

## 7. 실패 사례 분석

Phase B 에서 채움. 실행한 실제 사례가 없으므로 사례 id를 만들지 않는다.

## 8. 한계와 하지 못한 것

값만 변하는 공격, 정상 정책의 구조 변화, donor 주제/정상성·split 분리 가정,
ENT 토큰 교란, 다중 target 교체 시 문맥 왜곡, 불완전한 마스킹을 design.md에 기록했다.
α는 교환가능성 가정 아래 DSNT 오차 상한이지 전체 스택/주제별 FPR 보장이 아니다.
하네스 없이 실제 호출 수·성능·보정값·품질·지연을 측정하지 않았다.
진단 AUROC는 gate 통과 표본에 조건부이며 CI는 아직 산출하지 않는다.
호출 수는 논리적 호출 수이며 하네스의 실제 호출 집계를 대신하지 않는다.

## 9. 계약 변경 요청

없음.

## 10. 로컬 실행 절차

레포 루트 `/workspace/fsi-project`에서:

```sh
.venv/bin/python -m pytest tests/v3/dsnt tests/v3/tfm -q
.venv/bin/python -m pytest tests/v3 -q
.venv/bin/python tools/v3_check_ownership.py --owner dsnt --owner tfm
```

하네스 연결 시 먼저 실제 RunContext.llm으로 R10 프리플라이트를 수행한다.
G1/G2/G3·사전 등록 전에는 데이터 실험을 시작하지 않는다.
진단의 입력·출력 규약은 후보 README.md를 따른다. sealed 파일은 열지 않는다.
