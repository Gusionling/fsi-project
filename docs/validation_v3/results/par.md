# par 보고서 (Phase A)

작성 기준일: 2026-10-27 · 소유자: `par` · 브랜치: `claude/charming-maxwell-sww3ak` (소유권 검사는 이전 커밋 `cb6770e` 를 기준으로 par 변경분만 확인)

## 1. 요약

- PAR(근거 증명 답변 렌더러) 코드를 설계 의도대로 구현했다: 구조화 생성 → 코드 기반 증거 바인딩 → 고정 템플릿 렌더 → 입구·출구 게이트 조합, 그리고 info 로 새는 act 감시(`leak_check`), 커버리지 산출 스크립트.
- `pytest tests/v3/par` 49건 통과(네트워크 없음), `tools/v3_check_ownership.py --owner par` 는 `[OK]`.
- **실험 수치는 없다.** 이 단계의 산출물은 코드·테스트·문서뿐이고, 결과 표와 폐기 기준 판정은 Phase B 에서 채운다(R1).
- L2 와의 차이를 `design.md` 에 숨기지 않고 적었다. 핵심: `leak_check=true` 의 PAR 는 L2 의 act_detector 와 **같은 정의의 감시기**를 쓰므로 보안 지표가 L2 와 크게 다르리라 기대할 근거가 약하다. 차이가 나온다면 문장 단위 대체, 파싱 실패, 생성 경로 변경에서 올 가능성이 크다.
- 가장 불확실한 설계 결정 둘: (1) JSON 파손 시 동작, (2) 증거가 인정된 act 와 새어 나온 완료 단정에까지 감시기를 돌리는 확장(§4).

## 2. 실행 환경과 프리플라이트 결과

| 항목 | 결과 |
|---|---|
| 모드 | 온라인 가능(R10 통과: `OPENAI_API_KEY` 존재, `api.openai.com:443` 도달, 임베딩 1건 성공). 이 단계에서는 **실제 LLM 호출로 결과를 만들지 않았다** — 모든 검증은 테스트 안의 FakeLLM 으로 했다 |
| 모델 이름 | 생성·감시기 모두 `ctx.chatbot_model`(하네스가 gpt-4o-mini 로 채움) |
| 하네스 | `eval/v3/common` 은 import 하지 않았다(`test_par_defense.py::test_par_does_not_import_the_harness` 가 확인). 인터페이스(`eval/v3/interfaces.py`)만 보고 구현 |

## 3. 무엇을 만들었나

`eval/v3/candidates/par/`

| 파일 | 한 줄 설명 |
|---|---|
| `defense.py` | `PARDefense`(설정: `stack_b1`, `leak_check`). 전체 파이프라인 |
| `acts.py` | 세그먼트 스키마, 구조화 생성 프롬프트(`PROMPT_VERSION="v1"`), 파서(모델의 evidence 류 필드는 읽지 않고 버림) |
| `evidence.py` | 코드 기반 증거 바인딩(`bind`): 증거 ID 는 `status:<key>:<state>`, `ctx.trusted` 조회로만 만듦 |
| `render.py` | 고정 템플릿 상수 4개, 세그먼트 → 최종 답변 조립 |
| `leak.py` | info 세그먼트로 새는 act 감시기(독자 구현, 프롬프트 `LEAK_PROMPT_VERSION="v1"`) |
| `coverage.py` | 정상 케이스의 대체 문구 비율(전체·hard_negative_type 별·주제별) + 상위 20건 CSV |
| `design.md`, `README.md` | 1페이지 설계(L2 와의 차이, 우회 경로 6개), 사용법 |

`tests/v3/par/` — `par_stubs.py`(FakeLLM·가짜 챗봇·게이트·신뢰 소스), `conftest.py`, `test_par_{acts,evidence,defense,render,leak,coverage}.py`.

## 4. 설계 결정

| 결정 | 이유 | 대안 |
|---|---|---|
| **(불확실 1) JSON 파손**: 한 번 재시도하고(프롬프트에 안내 추가), 그래도 파손이면 고정 문구 `PARSE_FAILED_ANSWER`, `fallback_used=True`, `risk=0.0`, `flags.parse_failed=True` | 구조화 출력이 깨졌는데 비구조 답변을 내보내면 "JSON 을 깨뜨리기"가 PAR 를 끄는 우회가 된다. 그래서 보수적으로 막는다. `risk=0.0` 인 이유는 파싱 실패가 공격의 증거가 아니기 때문 | 비구조 답변으로 폴백(우회 가능), 재시도 없음(정상 질의 손실 증가), 재시도 2회 이상(비용) |
| 파싱 실패를 개입(`fallback_used`)으로 센다 | 고객이 답을 못 받으므로 정상 업무 지표(커버리지)에서는 오탐처럼 세어야 한다. 반대로 공격 케이스에서는 이 때문에 recall 이 부풀 수 있어, `coverage.py` 가 `parse_failed_rate` 를 따로 낸다 | 개입으로 세지 않음(지표가 실제 고객 경험과 어긋남) |
| **(불확실 2) 감시기 범위 확장**: info 세그먼트 전부 + 증거가 인정된 `completion_claim` act 에도 감시기를 돌려, 선언은 완료인데 실제 문장이 인증정보 요구이면 대체한다 | `act_type` 오표기로 증거 인정 규칙을 우회하는 것이 가장 쉬운 구멍이어서 | 지시서대로 info 만 감시(구멍을 그대로 둠). 확장은 L2 와의 차이를 더 줄이는 방향이므로 Phase B 에서 `leak_check=false` 와 비교해 효과를 본다 |
| 새어 나온 완료 단정도 `evidence.bind` 를 통과하면 출력한다(L2 와 같은 규칙) | 정당한 완료 안내를 `info` 로 쓴 정상 케이스를 불필요하게 막지 않으려고 | 감지되면 무조건 대체(커버리지 악화) |
| 감시기 응답 JSON 이 깨지면 누출 없음으로 취급하고 `flags.leak_parse_failed` 에만 남긴다 | 감시기를 못 믿는다고 모든 info 를 대체하면 커버리지가 무너진다. L2 의 act_detector 도 파싱 실패 시 False 로 둔다. 다만 이는 우회 경로 6 으로 `design.md` 에 적었다 | 파손 시 해당 케이스를 대체(정상 질의 손실) |
| `kind: act` 인데 `act_type` 이 두 종류가 아니면 `info` 로 취급해 감시를 받게 한다 | 행위 종류를 늘리지 않는다(I2). 숨을 곳을 주지 않는다 | 파싱 실패로 처리(정상 질의 손실), 무시 |
| 대체는 세그먼트 단위, 같은 종류 템플릿은 답변에 한 번만(처음 자리) | 정상 부분을 살리고 같은 문구가 반복되지 않게 | 답변 전체 대체(L2 방식) |
| 허용 `subject_key` 목록은 `case.trusted_fixture["application_status"]` 의 **키 이름**에서 가져와 user 메시지 끝에 붙인다. 상태 값은 모델에게 보이지 않는다 | L2 의 act_detector 와 같은 정보 수준. `TrustedStores` 에는 키를 나열하는 메서드가 없다 | 고정 어휘(데이터와 어긋날 수 있음). 계약 변경 요청 §9-1 |
| 생성은 `ctx.chatbot.answer` 가 아니라 `ctx.llm.complete` 로 직접 한다 | 구조화 출력(JSON 모드, system 접미사)이 필요해서. 시스템 프롬프트는 `ctx.chatbot_system_prompt` + 접미사, 청크 형식은 `ctx.chatbot.build_user_prompt`, 모델은 `ctx.chatbot_model` 로 기존 챗봇과 맞췄다 | `chatbot.answer` 래핑(구조화 불가) |
| 게이트가 막은 경우도 `risk=1.0`, 입구 게이트가 막으면 생성하지 않음 | 개입 여부가 risk 와 어긋나면 ROC 가 왜곡된다. `flags.risk_source` 로 PAR 고유 신호와 구분한다 | 게이트 차단은 risk 0 |
| 감시기는 `ctx.chatbot_model` 을 쓰고 온도 0, `max_tokens=400`, 항목 전체를 한 번 호출 | 호출 수를 줄이려고(추가 비용 1회) | 항목마다 호출(비용 ×n) |
| 시스템 접미사·감시기 프롬프트는 v1 초안이며 dev 로 튜닝하지 않았다 | 이 단계는 구현이다. 튜닝은 Phase B 의 dev 에서만 하고 버전·이유를 여기에 남긴다(R3) | |

## 5. 결과 표

Phase B 에서 채움. 이 단계에서는 실행 산출물이 없다(R1).

## 6. 폐기 기준 판정

Phase B 에서 채움. 참고용 기준(IDEAS §9.8, PREREG 가 확정): 정상 대체 문구 비율 10% 초과 / 독립 공격 집합 성공률 20% 초과 / 정상 거부율 5% 이하에서 L2 대비 recall 개선 +0.10 미만.

## 7. 실패 사례 분석

없음 (실험 없음).

## 8. 한계와 하지 못한 것

- **실제 모델로 구조화 출력이 얼마나 지켜지는지 모른다.** 파싱 실패율, 모델이 act 를 올바르게 선언하는 비율, 감시기 정확도 모두 미측정이다. FakeLLM 테스트는 분기 로직만 검증한다.
- **L2 와의 보안 지표 차이는 작을 가능성이 높다**(`design.md`). 이 구현이 L2 를 이기려고 감시기를 더 세게 만들지는 않았다.
- **다루는 행위는 2종뿐이다.** prompt_leak, 무결성(허위 수수료·기한·한도) 공격은 PAR 도 L2 도 막지 않는다. 계좌·URL·전화는 V4 몫이라 구현하지 않았다.
- **프롬프트 튜닝 없음.** 접미사·감시기 프롬프트는 초안(v1)이다.
- **파싱 실패를 개입으로 세므로** 공격 recall 이 부풀 수 있다. 분석 시 `flags.parse_failed` 로 반드시 분리해야 한다.
- **`subject_key` 와 실제 문장의 대상 일치는 검사하지 않는다**(우회 경로 2).
- 완료 상태 판정은 `completed`/`approved` 두 값뿐이다. 데이터에 다른 완료 표현이 있으면 정상 완료 안내가 대체될 수 있다.
- 감시기 호출은 케이스당 1회 추가된다(비용 지표에 반영해야 함).
- 하네스가 만드는 `predictions.jsonl` 의 필드(`case_id`, `fallback_used`, `blocked`, `flags`, `final_answer`)를 가정하고 `coverage.py` 를 썼다. 실제 파일과 다르면 `compute` 의 키만 고치면 된다. 실제 산출물로는 시험하지 못했다(가짜 산출물 테스트만).

## 9. 계약 변경 요청

1. **`TrustedStores` 에 상태 키 나열 메서드**(예: `status_keys(case)`)를 추가하면 좋겠다. 지금은 허용 `subject_key` 목록을 얻으려고 `case.trusted_fixture` 의 키를 직접 읽는다(L2 도 같은 방식이라 비교는 공정하지만, 인터페이스 밖 접근이다).
2. 그 밖의 필수 변경은 없다. 인터페이스(`complete`, `build_user_prompt`, `chatbot_system_prompt`, 게이트 두 개, `application_status`)로 충분했다.

## 10. 로컬 실행 절차

이번 실행은 온라인 모드였으나 실험 결과를 만들지 않았으므로 필수는 아니다. Phase B 에서(하네스·데이터가 머지된 뒤, `PREREG_v3.md` 이후):

```bash
pip install -r eval/v3/requirements.txt
export OPENAI_API_KEY=...
python -m pytest tests/v3/par -q
python -m eval.v3.common.run --defense eval.v3.candidates.par.defense:PARDefense --split dev --out eval/v3/results/par/dev_default/
python -m eval.v3.common.run --defense eval.v3.candidates.par.defense:PARDefense --split dev --set leak_check=false --out eval/v3/results/par/dev_noleak/
python -m eval.v3.candidates.par.coverage --predictions eval/v3/results/par/dev_default/predictions.jsonl \
       --cases eval/v3/data/cases_dev.jsonl --out-dir eval/v3/results/par/dev_default/coverage/   # 첫 관문: 정상 대체 비율
python -m eval.v3.common.compare --a eval/v3/results/par/dev_default --b eval/v3/results/_common/l2_dev   # L2 와 직접 비교
```
