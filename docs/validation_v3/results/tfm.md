# TFM-L Phase A 보고서

## 1. 요약

query-blind 추출·속성별 허가·표 전용 답변의 TFM-S/TFM-T를 구현했다.
스텁 기반 검증만 수행했다. 효과/폐기 기준 판정은 하지 않았다.
제안자는 Claude이며 공격 데이터에 온톨로지를 맞추지 않았다.

## 2. 실행 환경과 프리플라이트 결과

Python 3.12.14, 오프라인 FakeLLM 모드. 실제 모델 사용 없음.
RunContext 기본 모델 이름은 gpt-4o-mini이며 실제 호출했다는 의미가 아니다.
R10 (a) OPENAI_API_KEY의 존재만 확인(값 미열람).
(b) API 도달 및 (c) 실제 임베딩 프리플라이트는 수행하지 못함:
실제 RunContext.llm 클라이언트가 없고 common 구현은 범위 밖이다.
R6을 우회하는 직접 SDK 구현 없이 오프라인 구축까지만 수행했다.
온라인 준비를 주장하지 않으며 Phase B를 시작하지 않았다.

## 3. 무엇을 만들었나

모두 `eval/v3/candidates/tfm/` 아래:

- defense.py: TFMDefense S/T, B1 toggle·V4·거부율/추출실패/fallback 집계
- ontology.yaml: 일반 FAQ 속성의 고정 타입·범위/선택지·출처 권한
- extractor.py: 청크별 query-blind JSON 추출, 손상·중복 키·서비스 실패 처리
- licensing.py: 타입/출처/공식 엔티티·short_text 검증
- answerer.py: 기존 시스템/모델/청크 포맷을 사용한 질문+허가된 표 전용 답변
- design.md / README.md: 구현 현황·통로·결정·사용법

`tests/v3/tfm/`: owner 전용 FakeLLM·chatbot/gates/trusted/donors와 계약 테스트.
테스트 실행 기록: `eval/v3/results/tfm/phase_a_pytest.txt`.
테스트 수는 단위 테스트 실행 수이며 연구 성능 수치가 아니다.

## 4. 설계 결정

| 결정 | 이유 | 대안 |
|---|---|---|
| 추출기는 Chunk만 받고 질문을 받지 않음 | query-blind 경계 자체를 인터페이스로 고정 | query를 프롬프트에서만 빼는 약한 보장 |
| 출처는 Chunk 메타데이터, 행 키는 세 개로 제한 | 추출기의 출처 위조·설명문 전달 통로 차단 | 생성 source_type 신뢰 안 함 |
| 하나라도 추출 실패하면 전체 fallback | 조건/예외 누락한 부분 답변을 피함 | 부분 성공 표로 답변하면 가용성 증가 가능 |
| 빈 표도 fallback·항상 V4 | 표 밖 정보를 모델이 지어내지 않게 함 | 빈 표 LLM 질의 안 함 |
| 온톨로지 YAML은 JSON 부분집합 | 단일 명세·추가 의존성 없이 파싱 | PyYAML 추가 불필요 |
| 거부 행 비율은 보조 신호, 자동 차단 없음 | 중재 효과와 탐지 임계값 효과를 구별 | calib 임계값 튜닝 안 함 |
| 범위 내 0원·완료 안내 enum도 허가 | 불리한 새는 통로를 숨기지 않음 | 공격에 맞춰 유리한 값만 허용하지 않음 |

더 자세한 결정과 대안은 후보 design.md에 있다.

## 5. 결과 표

Phase B 에서 채움. 연구 실행 산출물 없음. author_model별·신뢰구간 결과도 미측정.

## 6. 폐기 기준 판정

Phase B 에서 채움. PREREG 미확정, G1/G2/G3 확인 전이므로 판정하지 않는다.

## 7. 실패 사례 분석

Phase B 에서 채움. 실제 사례를 실행하지 않아 사례 id를 만들지 않는다.

## 8. 한계와 하지 못한 것

TFM-L은 사실 무결성을 보장하지 않는다. 타입이 맞는 거짓, enum, short_text,
추출 누락/조작, 출처 메타데이터 위조, 답변기의 추론이 통로로 남는다.
일부 추출 실패의 전체 fallback은 가용성을 낮출 수 있다. 좁은 속성/선택지와
허가 정책은 정상 조건·예외·업무 순서를 잃을 수 있다. 정보 보존률은 미측정이다.
낮은 거부율은 안전/품질의 보장이 아니며 전면 추출 실패 때도 0일 수 있다.
알려진 통로·불변 조건·미결정 사항은 design.md에 기록했다.
TFM-O·하네스·데이터·PAR·성능 측정은 만들거나 수정하지 않았다.

## 9. 계약 변경 요청

없음.

## 10. 로컬 실행 절차

레포 루트 `/workspace/fsi-project`에서:

```sh
.venv/bin/python -m pytest tests/v3/dsnt tests/v3/tfm -q
.venv/bin/python -m pytest tests/v3 -q
.venv/bin/python tools/v3_check_ownership.py --owner dsnt --owner tfm
```

RunContext 스텁은 tests/v3/tfm/tfm_stubs.py에 있다. API 호출/키 설정은 테스트에 필요 없다.
하네스 연결 후 실제 RunContext.llm으로 프리플라이트를 하고 G1/G2/G3·사전 등록을
확인하기 전에는 Phase B를 시작하지 않는다. sealed를 열지 않는다.
