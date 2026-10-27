# DSNT 구현 설계 (Phase A, 진단용)

제안자는 Claude이며 이 코드는 제안을 검증할 구현이다. 효과를 입증하지 않았다.
CONTRACT와 interfaces.py를 변경하지 않는다. 데이터·sealed·공격 샘플은 읽지 않았다.

## 불변 조건 대비 구현 현황

| 조건 | 구현 | 검증 |
|---|---|---|
| D1 | 원래 query 그대로 answer 호출, context·원본 Case 불변 | 질문·context 불변/다중 target 테스트 |
| D2 | skeleton.py 한 패스로 NUM/DATE/MONEY/ACCT/URL/PHONE/ENT 마스킹, NFKC·공백 정규화 | 패턴별·공식 엔티티 우선순위 테스트 |
| D3 | 토큰 Levenshtein/max(토큰 수), embed는 ctx.llm.embed 배치 후 1−cosine | 작은 벡터·토큰 예, 잘못된 벡터 거부 |
| D4 | DonorPool.sample(topic,k,입력 전체 id,seed+target순번), 기본 k=5, k=10 지원 | donor 호출·k·seed 검사 |
| D5 | 원본 뼈대와 k개 교체 답변 뼈대 거리의 산술평균 | 정상 0 / 다른 답변 양수 테스트 |
| D6 | fit은 calib normal만 수용, s 저장; (1 + count(s_calib ≥ s))/(m+1), p ≤ α 의심 | 동률·경계·불충분 시 판정 보류 |
| D7 | α 낮춤→덜 차단, 높임→더 차단 | 코드 주석·방향 테스트 |
| D8 | B1(toggle) → 원답변 → V4 → DSNT, 조기 차단 시 donor 실행 없음 | 순서·short circuit 테스트 |
| D9 | 값만 다른 계좌 공격의 뼈대 동일함을 테스트로 명시 | V4에 의존하며 DSNT 효과로 계산하지 않음 |

## 설계 결정

| 결정 | 이유 | 대안 |
|---|---|---|
| target이 여러 개면 k번의 각 재실행에서 모두 교체. target마다 seed+순번으로 k donor 확보 | 공격 target 일부가 그대로 남는 것을 피하고 k개 반사실 답변이라는 정의를 유지 | 한 target씩 교체하면 별도 집계 규칙·비용 정의 필요 |
| fit에서는 B1/V4로 정상 표본을 걸러내지 않음 | 정상 s 전체 분포로 보정. run에서 두 gate 통과 후 동일 s 계산 | gate 통과 정상만 보정하면 조건부 선택 분포가 달라짐 |
| 보정 표본 부족이면 경고·s/p=null·risk 생략·원답변 유지 | 유효한 p≤α 판정이 불가능할 때 차단 효과를 꾸미지 않음. 앞선 B1/V4는 여전히 유효 | 자동 α 상향은 미등록 변경이라 하지 않음 |
| 최소 p = α인 경우 판정 허용 | 규칙은 p≤α이므로 m=19, α=.05에서는 최댓값 외삽 점수 차단 가능 | IDEAS의 p<α 설명과 구분 |
| fit 후 k/거리/embedding model/seed/챗봇 모델·시스템/공식 엔티티 변경은 오류 | 서로 다른 점수 정의의 보정을 섞지 않음. α 변경만 허용 | 묵시적 재보정은 calib 접근·호출을 숨김 |
| donor 부족·겹침·중복 또는 임베딩 영벡터/차원 오류는 명시적 예외 | 잘못된 실행을 정상 통과로 처리하지 않음 | 억지로 부족한 donor 반복·거리 0 대입하지 않음 |
| official entity > DATE > URL > PHONE > ACCT > MONEY > NUM, 정규식 1회 치환 | 공식 엔티티의 ENT 우선, 생성된 토큰 보호, 날짜/전화와 계좌의 패턴 겹침 해결 | 추출 LLM 추가는 별도 메커니즘이므로 제외 |

## α 해석과 한계

α는 **교환가능성 가정 아래 DSNT의 정상 오차 상한**이다. 낮추면 덜 막고,
높이면 더 막는다. 고위험에 더 엄격하려고 α를 낮추는 것은 반대 방향이다.
이 주장은 합성 데이터나 주제별 조건부 FPR, B1/V4를 포함한 전체 FPR의 보장이 아니다.
calib/dev 주제·donor 분포 차이, 정상 hard negative의 구조 변화는 교환가능성을 깨뜨릴 수 있다.

| 알려진 약점 | 결과/책임 |
|---|---|
| 계좌·URL 등 값만 바뀜 | 마스킹 때문에 안 보임. V4의 몫이며 V4 누락을 DSNT가 보완한다고 주장할 수 없음 |
| 공식 엔티티 ENT와 비공식 ACCT/URL 토큰이 다름 | 원래 값 외에 등록 여부가 뼈대에 남을 수 있어 순수 구조 분리의 교란 요인 |
| 정상 정책 변경·연체·인증 안내도 구조를 바꿈 | s가 커져 정상 오차 가능. 진단 CSV로 확인해야 함 |
| 정상 구조를 모방하는 공격·context에 있는 공격 | 거리가 작거나 target 교체 후에도 남을 수 있음 |
| donor 주제/정상성/split | Chunk에는 topic/label/split이 없음. DonorPool이 동일 주제·정상·split 분리를 보장해야 하며 후보는 id 겹침만 추가 검사 |
| 다중 target | target별 풀에 같은 donor가 등장할 수 있음. 동일 재실행 내 중복 donor가 문맥을 왜곡할 가능성 |
| 정규식 마스킹 | 한국어 숫자·축약 날짜·비표준 계좌·국제 전화·난독화 URL 등을 완전히 포괄하지 못함. 원문에 이미 있던 [NUM] 같은 문자열도 구별 불가 |
| edit/embed | edit는 표면 표현에 민감, embed는 모델의 행동 의미 구별 능력과 캐시/결정성에 의존 |
| 보정/생성 비용 | fit은 m×(1+k) 챗봇 호출, run은 gate 외 1+k 호출. embed는 케이스당 배치 1회 추가 |

llm_calls는 gate 제공 개수 + chatbot.answer 호출 수 + embed 배치 수다.
Chatbot에는 내부 호출 수 인터페이스가 없으므로 내부 재시도/다중 호출은 여기서 알 수 없다.
실제 비용의 단일 출처는 하네스의 RunContext.llm 집계이며, fit의 논리 호출은
calibration_llm_calls에 별도 저장한다.

## 진단 산출물

diagnostic.diagnose는 최상위 DefenseResult 필드+case_id인 predictions 행과 정확히 대응하는
Case 목록을 받는다. score_distribution.csv에 정상 hard negative 유형·공격 티어·엔티티 유무·저자별
케이스 점수를 남긴다. diagnostic.json은 정상 hard negative 대 공격 AUROC(동률 1/2),
scored 정상/hard negative의 p≤α FPR(Wilson 95%), 전체 정상 pipeline 개입률을 구분한다.
미채점 gate 차단은 s=0으로 채우지 않고 제외 개수를 표시한다. AUROC CI는 아직 제공하지 않는다.
경우에 따라 gate가 공격을 먼저 제거하므로 **이 AUROC는 DSNT까지 도달한 케이스의 조건부 진단**이다.
전체 방어 성능·executed recall은 하네스의 몫이다. 다른 설정·split의 결과를 한 분포로 섞지 않는다.
실행 산출물의 실제 하네스 직렬화가 다르면 호출 측에서 이 문서의 행 형식으로 변환해야 한다.

## 미결정 사항

- 다중 target에서 개별 교체와 동시 교체 중 어느 진단이 더 의미 있는가? 현재 동시 교체이며 dev 실험 전 고정·검토 필요.
- 마스킹의 ENT/일반 토큰 차이가 구조 진단을 얼마나 교란하는가? 공격에 맞춰 규칙을 바꾸지 않았고 미측정.
- k/거리/α의 최종 설정과 폐기 기준은 사용자 사전 등록 전까지 미확정. Phase B 미실행.
- 계약 변경 요청 없음.
