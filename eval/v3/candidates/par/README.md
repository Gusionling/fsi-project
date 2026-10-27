# PAR (근거 증명 답변 렌더러) 사용법

설계: `design.md`. 인터페이스: `eval/v3/interfaces.py` (`PARDefense` 는 `Defense` 구현). 이 패키지는 `eval/v3/common` 을 import 하지 않는다.

## 실행 (Phase B, 하네스가 준비된 뒤)

```bash
python -m eval.v3.common.run --defense eval.v3.candidates.par.defense:PARDefense --split dev \
       --out eval/v3/results/par/<run_id>/                      # 기본: stack_b1=true, leak_check=true
python -m eval.v3.common.run --defense eval.v3.candidates.par.defense:PARDefense --split dev \
       --set leak_check=false --out eval/v3/results/par/<run_id>_noleak/   # 구조화 선언만의 효과 (ablation)
python -m eval.v3.common.run ... --set stack_b1=false ...        # 입구 게이트 없이
```

## 커버리지 (정상 케이스 중 대체 문구로 떨어지는 비율 — 첫 관문)

```bash
python -m eval.v3.candidates.par.coverage --predictions eval/v3/results/par/<run_id>/predictions.jsonl \
       --cases eval/v3/data/cases_dev.jsonl --out-dir eval/v3/results/par/<run_id>/coverage/
```
`coverage.json`(전체·hard_negative_type 별·주제별 fallback/gate_block/parse_failed/any 비율, Wilson 95%)과 `fallback_top20.csv` 가 나온다.

## 설정 (`--set key=value`)

| 키 | 기본 | 뜻 |
|---|---|---|
| `stack_b1` | true | 입구 B1 게이트 사용 |
| `leak_check` | true | info 세그먼트로 새는 완료 단정·인증정보 요구 감시 |

## 점수와 플래그

`scores["risk"]` = 증거 없는 act(선언된 것 + 감시기가 찾은 것)를 대체했으면 1.0, 아니면 0.0. 게이트가 막은 경우도 1.0 이다(`flags.risk_source` 로 구분: `rejected_acts` / `gate` / `parse_failed` / `none`).
`flags`: `acts_declared`, `acts_licensed`, `acts_rejected`, `leak_detected`, `leak_rejected`, `parse_failed`, `parse_retry_used`, `rejected_acts`(대체된 문장·사유), `licensed_evidence`, `ignored_field_count`(모델이 보낸 evidence 류 필드 수 — 읽지 않음), `blocked_by`.

## 테스트

```bash
python -m pytest tests/v3/par -q      # 네트워크 없음
```

## 프롬프트 버전

`acts.PROMPT_VERSION`, `leak.LEAK_PROMPT_VERSION` (둘 다 "v1"). 프롬프트를 바꾸면 버전을 올리고 par.md 의 설계 결정 표에 이유를 적는다. 이 단계에서는 dev 로 튜닝하지 않았다.
