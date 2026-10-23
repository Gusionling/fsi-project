# v3 실행 순서 (RUNBOOK) — 사람이 할 일

에이전트 프롬프트는 같은 폴더의 `A1`~`A4`, `B1`, `B2` 파일이다. 이 문서는 **사람이 하는 일의 순서**만 다룬다.

## 역할 분배

| 에이전트 | 맡은 일 | 이유 |
|---|---|---|
| Claude Code (세션 3개) | `harness` 하네스·기준선 · `data` 데이터 · `par` PAR | 기존 레포를 가장 잘 아는 쪽이 공통 기반을 만든다. PAR 는 GPT 가 낸 아이디어라 **제안자가 아닌 모델**이 구현한다 |
| Codex (작업 1개) | `dsnt` + `tfm` | DSNT·TFM-L 은 Claude 가 낸 아이디어라 제안자가 아닌 모델이 구현한다. 또 데이터를 만든 모델(Claude)과 구현하는 모델이 달라 같은 저자 편향이 줄어든다. DSNT 는 1일 진단이라 부담이 작다 |

## 0. 한 번만 하는 환경 설정 (확인한 공식 문서 기준)

| | Claude Code 클라우드 환경 | Codex 클라우드 환경 |
|---|---|---|
| 네트워크 | 기본 `Trusted` 목록에는 `api.openai.com` 이 **없다**. 환경을 `Custom` 으로 바꾸고 허용 도메인에 `api.openai.com` 추가 | 에이전트 인터넷은 **기본 꺼짐**. `On` 으로 켜고 허용 도메인에 `api.openai.com` 추가. 권장 설정이 `GET/HEAD/OPTIONS` 만 허용인데 **POST 가 막히므로 메서드 제한을 풀어야** 한다 |
| API 키 | 환경변수 `OPENAI_API_KEY` (에이전트가 읽을 수 있음). 네트워크 시크릿 방식도 있으나 SDK 가 키를 요구하므로 환경변수가 단순 | **환경변수**로 넣는다. "Secrets" 는 셋업 스크립트에서만 쓰이고 에이전트 단계 전에 제거된다 |
| 셋업 스크립트 | `pip install -r eval/v3/requirements.txt` | 동일 |
| Phase A | A1·A2·A3 는 네트워크 없이도 대부분 진행 가능 (A2 의 T4 B1 시험만 네트워크 필요) | A4 는 네트워크 불필요 |
| Phase B | 네트워크 필수 | 네트워크 필수 |

- 에이전트에게 키가 노출되므로 **이 프로젝트 전용 키**를 만들고 사용 한도를 걸어 둔다.
- 위 설정이 불확실하면 에이전트의 프리플라이트(R10)가 실패를 알려 준다. Phase A 는 오프라인 모드로 진행되고, Phase B 는 멈춘다.
- 근거 문서: Claude Code `cloud-environments` (code.claude.com/docs/en/cloud-environments), Codex 클라우드 환경·인터넷 접근 (learn.chatgpt.com/docs/environments/cloud-environment, learn.chatgpt.com/docs/cloud/internet-access).

## 1. 스켈레톤을 main 에 먼저 넣는다 (G0)

번들을 레포 루트에 풀고:

```bash
bash setup_v3_skeleton.sh
git checkout -b v3/skeleton
git add docs/validation_v3 eval/v3 tests/v3 tools/v3_check_ownership.py .gitignore
git commit -m "chore(v3): 검증 계약서·인터페이스·스켈레톤 추가"
# main 에 머지/푸시 (PR 이든 직접이든)
```

`setup_v3_skeleton.sh` 와 번들의 `prompts/` 는 커밋해도 되고 안 해도 된다. 에이전트가 반드시 봐야 하는 것은 `CONTRACT.md`, `IDEAS.md`, 스키마 2개, `interfaces.py`, `tools/v3_check_ownership.py` 이다.

## 2. Phase A — 4개를 동시에 시작

| 순서 | 에이전트 | 프롬프트 | 시작점 |
|---|---|---|---|
| ① | Claude Code 세션 1 | `A1_harness_claude_code.md` (Part 1) | main |
| ② | Claude Code 세션 2 | `A2_data_claude_code.md` | main |
| ③ | Claude Code 세션 3 | `A3_par_claude_code.md` | main |
| ④ | Codex | `A4_dsnt_tfm_codex.md` | main |

네 작업은 소유 경로가 겹치지 않으므로 서로 기다릴 필요가 없다.

## 3. Phase A 결과를 머지 (G1)

브랜치마다:

```bash
git fetch origin
git checkout <브랜치>
python tools/v3_check_ownership.py --owner <harness|data|par|dsnt --owner tfm>   # [OK] 여야 함
```

그다음 main 에 머지한다. 순서는 상관없고 충돌이 없어야 한다 (충돌이 나면 그것이 규칙 위반의 증거다).

```bash
git checkout main
git merge --no-ff <브랜치>      # 4번
python -m pytest tests/v3 -q
python -m eval.v3.common.selfcheck
python eval/v3/data/verify_counts.py
```

## 4. 기준선 실행 (G2)

A1 의 **Part 2** 프롬프트를 붙여 넣는다 (harness 세션을 이어가거나 새 세션에서 main 최신 기준으로).
- executed set 에서 T2·T4·엔티티 없는 공격이 각각 E ≥ 60 인지 본다.
- 모자라면 `A2` 하단의 "보충 라운드" 프롬프트를 data 세션에 붙여 넣고, 머지한 뒤 executed set 을 다시 계산한다.
- `judge_audit_dev.csv` 를 직접 훑어 본다. judge 가 틀리면 모든 숫자가 틀린다.

## 5. 사전 등록 동결 (G3)

Phase A 가 도는 동안 `docs/validation_v3/PREREG_v3.md` 를 확정한다 (폐기 기준 수치, 통계 규칙, 데이터 사용 규칙).
G2 까지 끝나면 PREREG 를 main 에 넣고 **사용자가** 태그를 만든다:

```bash
git tag protocol-frozen-v3 && git push origin protocol-frozen-v3
```

에이전트는 태그를 만들지 않는다.

## 6. Phase B — 2개를 동시에 시작

| 에이전트 | 프롬프트 |
|---|---|
| Codex | `B1_dsnt_tfm_codex.md` |
| Claude Code | `B2_par_claude_code.md` |

둘 다 에이전트가 시작 전 게이트(PREREG·태그·executed set·selfcheck·프리플라이트)를 검사하고, 어긋나면 멈춘다.

## 7. 판정 (G4)

세 보고서(`docs/validation_v3/results/{dsnt,tfm,par}.md`)의 §6 폐기 기준 판정 표를 본다.
- 모두 폐기: "L2(B1+V4+정책 검사)가 현재 최선, 새 메커니즘은 사전 등록 기준 미달" 이 결론이다. 유효한 결과다.
- 하나 이상 통과: Phase C (동결 후 sealed 최종 평가, 적응형 공격 확대, holdout v2 공격 데이터 신규 제작) 를 계획한다.

## 참고: 막혔을 때

| 증상 | 조치 |
|---|---|
| 에이전트가 "소유 경로 밖 변경" 으로 멈춤 | 정상 동작이다. 계약 변경이 정말 필요한지 판단해 main 의 동결 파일을 사람이 고친다 |
| 머지 충돌 | 규칙 위반이다. 충돌 난 파일의 소유자와 `git log` 로 누가 건드렸는지 확인하고 소유자 쪽만 남긴다 |
| 프리플라이트 실패 | 0절의 네트워크·키 설정 확인 |
| E 부족 | 4절의 보충 라운드 |
