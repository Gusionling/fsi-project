# v3 하네스 사용법 (후보 구현자용)

모든 방어(기준선 `no_defense`·`l0`·`l1`·`l2`, 후보 DSNT·TFM·PAR)를 **같은 데이터·같은 지표**로 돌리는 공통 기반이다.
계약은 `docs/validation_v3/CONTRACT.md`, 구현 근거와 한계는 `docs/validation_v3/results/harness.md`.

## 준비
```bash
pip install -r eval/v3/requirements.txt
export OPENAI_API_KEY=...        # 코드·로그·캐시에 남지 않는다. 캐시: .cache/v3/llm/
python -m pytest tests/v3 -q      # 네트워크 없이 통과해야 한다
python -m eval.v3.common.selfcheck   # 마지막 줄 SELFCHECK OK
```

## 순서
```bash
# 1) 방어 없이 돌려 executed set E 를 고정 (split 당 1회, 이미 있으면 --force 없이는 덮어쓰지 않음)
python -m eval.v3.common.executed_set --split dev
python -m eval.v3.common.audit                      # judge 감사표 CSV (사람이 40건 확인)

# 2) 기준선·후보 실행 (같은 명령을 다시 돌리면 이어서 한다. 설정이 다르면 거부)
python -m eval.v3.common.run --defense l2 --split dev --out eval/v3/results/_common/l2_dev
python -m eval.v3.common.run --defense eval.v3.candidates.par.defense:PARDefense --split dev \
       --set stack_b1=true --out eval/v3/results/par/run1
#   --limit N : 앞 N 케이스만 (스모크 테스트). E 는 일부만 쓰이므로 metrics 에 E_restricted=true 로 표시된다.

# 3) 같은 E 위에서 비교 (차이 = a - b, paired bootstrap 95%, B=10,000, seed 고정)
python -m eval.v3.common.compare --a eval/v3/results/par/run1 --b eval/v3/results/_common/l2_dev
```

## 산출물 (`--out`)
| 파일 | 내용 |
|---|---|
| `predictions.jsonl` | 케이스당 한 줄: 최종 답변, blocked/fallback/intervened, scores, flags, judge 판정과 근거, LLM 호출 수 |
| `metrics.json` | executed recall, ASR_after, FPR(+hard negative), 정상 답변 정확도, 무결성, tier·intent·entity·author_model 별 분해, risk 가 있으면 ROC-AUC 와 calib 임계값 |
| `run_meta.json` | git_sha, dirty, 방어·설정, split 과 파일 sha256, 모델 이름, seed, 케이스 수, LLM 호출 수(logical/api, tag 별), 시각 |
| `calib_scores.jsonl` | (risk 점수가 있는 방어만) calib 정상 케이스의 risk — 임계값을 정하는 데 쓴다 |

## 후보가 알아야 할 것
- 방어는 `Defense`(`eval/v3/interfaces.py`)를 구현한다. LLM 은 `ctx.llm.complete(...)` 로만, 챗봇은 `ctx.chatbot.answer` / `ctx.chatbot.build_user_prompt`,
  같은 시스템 프롬프트·모델은 `ctx.chatbot_system_prompt` / `ctx.chatbot_model`.
- L1 의 두 문은 `ctx.gates.b1_chunk_gate(case, ctx)` / `ctx.gates.v4_answer_gate(case, answer, ctx)` 로 직접 조합한다.
- 점수가 있으면 `scores["risk"]` (높을수록 의심). 개입 = `blocked or fallback_used`.
- 같은 입력에 같은 출력: temperature 0, 캐시, `ctx.seed`. `llm.complete(tag=...)` 의 tag 는 호출 수 집계용이다.
- `test_sealed` 는 사용자가 `V3_ALLOW_SEALED=1` 을 설정했을 때만 읽힌다. 에이전트는 설정하지 않는다.
- judge 모델은 기본 `gpt-4.1-mini`, 환경변수 `V3_JUDGE_MODEL` 로 바꾼다 (방어가 쓰는 gpt-4o-mini 와 달라야 한다).
