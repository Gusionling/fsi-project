# DSNT (진단용, Phase A)

`DSNTDefense()`를 동결 Defense 인터페이스로 사용한다. 먼저 **calib 정상**만으로
`fit(cases, ctx)` 후 `run(case, ctx)` 한다. 하네스 import는 필요 없다.
기본 config: `donors_k=5`, `dist_kind=edit`, `alpha=0.05`, `stack_b1=true`.
`donors_k=10`, `dist_kind=embed`도 지원한다. embed는 `ctx.llm.embed`만 사용한다.
모델·seed·거리 등 점수 정의가 달라지면 재보정해야 한다.

레포 루트에서 오프라인 검증:

```sh
.venv/bin/python -m pytest tests/v3/dsnt -q
.venv/bin/python tools/v3_check_ownership.py --owner dsnt --owner tfm
```

진단: `diagnostic.diagnose(prediction_rows, cases, out_dir, alpha=.05)`.
각 prediction 행은 `case_id`와 최상위 `DefenseResult` 필드를 가진다.
실제 하네스 산출물에서 읽은 행만 사용하고 동일 dev/calib split·설정·seed·모델 실행만 묶는다.
`out_dir`는 소유 경로 `eval/v3/results/dsnt/<run_id>/`로 지정한다.
CSV는 케이스별 점수와 그룹 메타데이터, JSON은 군별 AUROC·FPR이다.
미채점은 제외 개수를 명시한다. 데이터 로더/러너/평가 judge는 만들지 않았다.
실행 예시는 호출 형식이며 실험 결과가 아니다. 상세 제한은 design.md에 있다.
