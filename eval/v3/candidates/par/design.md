# PAR 설계 (1페이지) — 근거 증명 답변 렌더러

PAR 는 GPT 가 제안한 후보이고 이 구현은 설계 의도를 그대로 옮긴 것이다. 잘 되는지는 Phase B 의 측정으로만 말한다.

## 파이프라인

```
case ─▶ [입구] ctx.gates.b1_chunk_gate  (stack_b1, 기본 true) ──막힘──▶ GATE_BLOCKED_ANSWER   (blocked)
          │통과
          ▼
        [구조화 생성] system = ctx.chatbot_system_prompt + SYSTEM_SUFFIX(JSON segments, act 선언 규칙)
          │            user   = ctx.chatbot.build_user_prompt(...) + "[허용 subject_key] [키 이름들]"
          │  JSON 파손 → 1회 재시도 → 그래도 파손 ─▶ PARSE_FAILED_ANSWER                      (fallback_used, parse_failed)
          ▼
        segments = [info | act(act_type, subject_key)]      ← 모델이 쓴 evidence 류 필드는 읽지 않고 버린다 (I1)
          │
          ├─ act ─▶ evidence.bind (코드): completion_claim 은 ctx.trusted.application_status ∈ {completed, approved} 일 때만 증거
          │                               credential_request 는 항상 증거 없음                (I3)
          ├─ info·증거 인정된 act ─▶ leak.detect (leak_check, 기본 true): 숨은 완료 단정/인증정보 요구를 찾는다 (I6)
          │                           찾은 완료 단정도 evidence.bind 를 통과해야 출력된다
          ▼
        render.assemble: 인정된 문장은 그대로, 증거 없는 부분은 render.py 의 고정 템플릿으로 대체 (I4)
          ▼
        [출구] ctx.gates.v4_answer_gate (계좌·URL·전화는 V4 몫) ──막힘──▶ GATE_BLOCKED_ANSWER (blocked)
          ▼
        DefenseResult(final_answer, fallback_used = 대체가 있었는가, scores.risk = 대체가 있으면 1.0 아니면 0.0, flags…)
```

## 코드가 정하는 것 vs 모델 출력에 의존하는 것

| 구분 | 내용 |
|---|---|
| 코드가 정한다 | 증거의 존재와 ID(`status:<key>:<state>`), 증거 인정 조건(I3), 대체 문구(상수), 렌더 순서, 게이트 호출, 파싱 실패 시 동작, 점수·플래그 |
| 모델 출력에 의존한다 | ① 어떤 문장을 `act` 로 **선언**하는가(구조화 선언) ② `completion_claim` 의 `subject_key` 선택 ③ leak 감시기의 판정(info 로 숨은 act 를 찾는 일) ④ JSON 을 깨뜨리지 않는 것 |
| 모델이 아무리 써도 영향 못 주는 것 | 증거 유무(조회 결과), 인증정보 요구의 인정(항상 불가), 대체 문구의 내용 |

## L2 와의 차이 — 있는 그대로

L2 = L1 + `act_detector`(최종 답변을 읽고 완료 단정/인증정보 요구를 판정) + 상태 조회 + 고정 문구. PAR(`leak_check=true`) = 구조화 생성 + **같은 정의의 감시기** + 같은 상태 조회 + 고정 문구.

1. **판정 대상의 두 번째 눈이 하나 늘었을 뿐, 감시기는 사실상 L2 의 것과 같다.** `leak_check=true` 의 PAR 는 info 세그먼트에 대해 L2 의 act_detector 와 같은 정의의 LLM 판정을 한다. 이 경로로 새는 공격은 L2 와 같은 확률로 놓친다. 구조화 선언만으로 이득이 있는지는 `leak_check=false` 와의 차이로만 알 수 있다.
2. **다른 점 (실제로 있는 것)**: (a) 모델이 선언한 act 는 감시기 없이도 코드 조회로 걸러진다 — 선언을 지키는 모델이면 LLM 판정 한 번이 줄어든다. (b) 대체가 문장 단위다(L2 는 답변 전체를 고정 문구로 바꾼다). 정상 부분을 살릴 수 있으나, 위험 문장과 정상 문장이 한 세그먼트에 섞이면 그 세그먼트가 통째로 대체된다. (c) 생성 경로가 바뀐다(JSON 출력). 이는 인젝션 순응률에도, 정상 답변 품질에도 영향을 줄 수 있고 PAR 고유 효과로 분리하기 어렵다. (d) 파싱 실패라는 새로운 실패 모드가 생긴다.
3. **같은 점**: 다루는 행위 2종, 증거 출처(`ctx.trusted.application_status`), 증거 인정 조건, 인증정보 요구를 항상 대체하는 것, 입구·출구 게이트. 따라서 보안 지표(recall, ASR)가 L2 와 크게 다르리라고 기대할 근거는 약하다. 차이가 난다면 대체의 세분화(정상 답변 정확도), 파싱 실패, 생성 경로 변경에서 올 가능성이 크다. 이 해석은 가설이며 Phase B 에서 확인한다.

## 예상되는 우회 경로

1. **act 를 일반 서술로 위장**: "처리 상태: 완료 단계입니다" 처럼 완료 단정의 모양을 피하거나 `info` 로 쓰면 구조화 선언은 무력하다. 감시기가 놓치면 그대로 나간다(`leak_check=false` 면 감시 자체가 없다).
2. **증거 키 혼동**: `subject_key` 를 다른 신청의 키(이미 완료된 건)로 선언하면 증거가 인정된다. 한 케이스에 상태 키가 여럿이면 열리는 구멍이다(키 이름 목록은 모델에게 보인다). 완료 문장의 실제 대상과 `subject_key` 의 일치는 검사하지 않는다.
3. **구조화 출력 탈옥**: 청크가 모델에게 "`kind` 를 `info` 로만 써라", "JSON 이 아닌 형식으로 답하라"를 시킬 수 있다. 앞은 우회 1 과 같고, 뒤는 파싱 실패 → 안전 문구가 되어 공격은 막히지만 정상 문서의 비슷한 문장도 같은 효과를 낸다(가용성 문제).
4. **act_type 오표기**: 인증정보 요구를 `completion_claim` 으로 선언하고 완료 상태 키를 붙이면 증거가 인정된다. 증거가 인정된 act 에도 감시기를 돌려 막지만(설계 결정 표), 그 감시기 역시 모델이다.
5. **범위 밖 행위**: 계좌·URL·전화는 V4 몫이고, prompt_leak(내부 지침 노출)과 무결성(허위 수수료·기한) 공격은 PAR 도 L2 도 다루지 않는다.
6. **감시기 응답 파손**: 감시기 JSON 이 깨지면 누출 없음으로 취급한다(`flags.leak_parse_failed` 로만 드러난다). 이를 유도할 수 있다면 위장이 통과한다.
