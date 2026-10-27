# TFM-L (TFM-S / TFM-T, Phase A)

`TFMDefense()`는 기본 S 모드. `ctx.config['mode']='T'`로 제한된 short_text를 추가한다.
`stack_b1=false`로 입구만 끌 수 있으며 출구 V4는 항상 사용한다.
`fit`은 no-op: 거부율은 보조 점수이며 독립적인 차단 임계값을 학습하지 않는다.
모든 LLM 호출은 ctx.llm.complete로 하고 실제 하네스는 import하지 않는다.

레포 루트에서 오프라인 검증:

```sh
.venv/bin/python -m pytest tests/v3/tfm -q
.venv/bin/python tools/v3_check_ownership.py --owner dsnt --owner tfm
```

온톨로지는 YAML 1.2 JSON 부분집합이다. 각 추출 행은 정확히
`{"attribute":"fee", "type":"number", "value":500}` 같은 세 키만 갖는다.
출처는 Chunk.source_type으로 묶는다. 답변기는 허가된 표와 질문만 받는다.
JSON 손상/서비스 오류가 하나라도 있거나 표가 비면 고정 fallback을 반환한다.
실제 평가 데이터/성능 결과는 없으며 TFM-O도 없다. 한계·통로는 design.md에 있다.
