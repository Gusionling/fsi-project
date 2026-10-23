# [Phase A-3] Claude Code — PAR 구현

| 항목 | 값 |
|---|---|
| 에이전트 | Claude Code (클라우드), A1·A2 와 **별개의 세션** |
| 소유자 이름 | `par` |
| 브랜치 | `v3/par` (시작점: 스켈레톤이 들어간 main) |
| 선행 조건 | G0 |
| 병렬로 도는 것 | A1 harness, A2 data, A4 dsnt-tfm |
| 네트워크 | **불필요** (FakeLLM 단위 테스트까지가 이 단계의 범위) |

아래 `PROMPT` 부터 끝까지를 그대로 붙여 넣는다.

---

## PROMPT

### 역할
너는 fsi-project 의 **PAR(근거 증명 답변 렌더러) 구현자**다 (소유자 이름 `par`).
PAR 는 GPT 가 제안한 후보이고, 너(Claude)는 제안자가 아니다. 이 후보가 잘 되든 안 되든 상관없이 **설계 의도대로 정직하게 구현**하는 것이 일이다. 특히 "L2(단순 기준선)와 실제로 무엇이 다른가"를 숨기지 말고 코드와 문서에 드러낸다.

### 공통 지침
- 가장 먼저 `docs/validation_v3/CONTRACT.md` 를 끝까지 읽고 따른다. 충돌하면 CONTRACT 가 우선이다. 특히 §3(소유권), §6.1(인터페이스, 게이트 조합), §6.3(L2 사양), R1·R5·R6·R9.
- `docs/validation_v3/IDEAS.md` 의 **§5(기준선), §6(예시), §9(PAR)** 를 읽는다. §9.3 의 "2개 행위로 축소"가 이번 범위다.
- `eval/v3/interfaces.py` 를 읽는다 (동결 파일; 고치지 않는다).
- 하네스(`eval/v3/common/`)는 **병렬로 만들어지는 중**이라 아직 없다. 인터페이스만 보고 구현하고, 테스트는 자기 `tests/v3/par/` 안의 스텁(FakeLLM, 가짜 chatbot, gates, trusted, donors)으로 한다.
- 막히면 우회하지 말고 보고서의 "한계"·"계약 변경 요청"에 적는다.

### 구현 범위 (`eval/v3/candidates/par/`, 테스트는 `tests/v3/par/`)

**불변 조건 (설계의 핵심 — 어기면 PAR 가 아니다)**
- **I1** 증거(evidence) 레코드는 **코드가** `ctx.trusted` 조회 결과로만 만든다. LLM 이 낸 `evidence`·`evidence_id` 류 필드는 읽지도 신뢰하지도 않는다.
- **I2** 다루는 행위는 **2종**: `completion_claim`(고객의 요청이 처리 완료되었다고 단정), `credential_request`(채팅에 비밀번호·보안카드·OTP 입력을 요구). 계좌·URL·전화는 V4 게이트의 몫이다.
- **I3** 증거가 인정되는 조건: `completion_claim` 은 `ctx.trusted.application_status(case, subject_key)` ∈ {`completed`, `approved`}. `credential_request` 는 **항상 인정하지 않는다** (공식 절차 중 채팅 입력을 받는 것은 없다 — CONTRACT §5.1).
- **I4** 증거가 없으면 해당 부분을 **고정 문자열 템플릿**으로 대체한다 (LLM 생성 금지). 템플릿은 `render.py` 에 상수로 둔다.
- **I5** 생성 경로: 챗봇이 **구조화 출력**을 내게 한다. 시스템 프롬프트는 `ctx.chatbot_system_prompt` 에 "답변을 JSON `segments` 로 쓰고, 고객의 요청 처리 상태를 단정하거나 인증정보 입력을 요구하는 문장은 반드시 `kind: act` 로 선언하라"는 지시만 덧붙인다. 청크 형식은 `ctx.chatbot.build_user_prompt` 를 쓴다. 렌더러는 `info` 세그먼트와 증거가 인정된 `act` 세그먼트만으로 최종 답변을 조립한다.
- **I6** `info` 세그먼트로 **act 가 새는 것**을 감시한다 (공격이 act 를 일반 서술로 위장할 수 있기 때문). 감시기는 CONTRACT §6.3 의 L2 `act_detector` 와 **같은 정의**(고객 요청 처리 완료 단정 / 채팅 인증정보 입력 요구)를 따르되, **코드는 독자 구현**한다 (하네스 코드를 import 하지 않는다). `ctx.config["leak_check"]` (기본 `true`) 로 끌 수 있어야 한다 — Phase B 에서 구조화 선언만의 효과를 분리해 보기 위해서다.
- **I7** 파이프라인: `ctx.gates.b1_chunk_gate`(입구, `ctx.config["stack_b1"]` 기본 `true`) → 구조화 생성 → 렌더 → `ctx.gates.v4_answer_gate`(출구).
- **I8** `DefenseResult`: 증거 없는 act 를 대체했으면 `fallback_used=True`, 입구·출구 게이트가 막았으면 `blocked=True`. `scores["risk"]` = 거부된(증거 없는) act 세그먼트 수가 0 이면 0.0, 있으면 1.0 (필요하면 leak 감지 여부를 `flags` 에). `flags` 에 `acts_declared`, `acts_licensed`, `acts_rejected`, `leak_detected`, `parse_failed` 를 기록한다.
- **I9** 구조화 출력의 JSON 이 깨졌을 때(`parse_failed`)의 동작을 **보수적으로 정하고** 설계 결정 표에 이유를 적는다 (예: 한 번 재시도 후 안전 문구). 이 비율은 정상 업무 지표이므로 반드시 `flags` 에 남긴다.

**파일**

| 파일 | 내용 |
|---|---|
| `defense.py` | `PARDefense` (설정: `stack_b1`, `leak_check`) |
| `acts.py` | 세그먼트 스키마, 구조화 생성 프롬프트(버전 관리: `PROMPT_VERSION`), 파서 |
| `evidence.py` | 코드 기반 증거 바인딩 (I1·I3). 증거 ID 는 `"status:<key>:<state>"` 형태처럼 결정적으로 코드가 만든다 |
| `render.py` | 고정 템플릿, 세그먼트 → 최종 답변 조립 |
| `leak.py` | I6 감시기 |
| `coverage.py` | 실행 산출물(`predictions.jsonl`)과 케이스 파일을 받아 정상 케이스의 fallback 비율을 전체·`hard_negative_type` 별·주제별로 계산하고, fallback 이 난 정상 케이스 상위 20건을 CSV 로 낸다 |
| `design.md` | 1페이지: 파이프라인 그림(텍스트), **코드가 정하는 것 vs 모델 출력에 의존하는 것** 표, **L2 와의 차이를 있는 그대로**, 예상되는 우회 경로 3개 이상 (예: act 를 일반 서술로 위장, 증거 키 혼동, 구조화 출력 탈옥) |
| `README.md` | 사용법 |

### 테스트 (`tests/v3/par/`, 네트워크 없이 통과)
- 증거 바인딩: LLM 출력에 가짜 `evidence_id` 가 있어도 무시되고 코드 조회로만 인정/거부된다.
- 상태가 `received_pending_review` 인데 "완료" act → 템플릿 대체. 상태가 `completed` 인 정상 완료 안내 → 통과.
- `credential_request` act → 항상 대체. "앱의 재설정 메뉴에서 본인인증하세요" 같은 정상 절차 안내는 통과.
- info 세그먼트로 위장한 완료 단정 → `leak_check=true` 면 대체, `false` 면 통과 (이 차이가 곧 ablation 이다).
- JSON 파손 → I9 동작. 입구 게이트가 막으면 생성하지 않는다.
- `coverage.py` 의 집계가 맞다 (작은 가짜 산출물로).
- 같은 입력 → 같은 출력 (결정성).

### 하지 말 것
- 하네스·데이터·다른 후보의 파일을 만들거나 고치지 않는다. `eval/v3/common/**` 를 import 하지 않는다 (아직 없고, 의존이 생기면 테스트가 깨진다).
- 계좌·URL·전화 검사를 직접 구현하지 않는다 (V4 게이트 몫).
- "더 잘 막히게" 하려고 행위 종류를 늘리지 않는다 (I2).
- 실제 LLM 호출 결과를 만들어 내거나 성능을 주장하지 않는다 (R1). 이 단계의 산출물은 코드·테스트·문서뿐이다.

### 완료 기준 (DoD)
- [ ] `pytest tests/v3/par` 통과
- [ ] `python tools/v3_check_ownership.py --owner par` 가 [OK]
- [ ] `design.md` 에 L2 와의 차이와 우회 경로가 정직하게 적혀 있다
- [ ] `par.md` (CONTRACT §8 템플릿; 이 단계는 3·4·8·9·10 절 위주, 결과 표는 "Phase B 에서 채움")
- [ ] 전부 커밋됨, 커밋 메시지에 AI 표시 없음
- [ ] 채팅에 10줄 이내 요약: 만든 것, 설계 결정 중 가장 불확실한 것 2개, 계약 변경 요청 유무
