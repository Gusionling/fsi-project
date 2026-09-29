# QueryIPI

RAG 청크 프롬프트 인젝션 탐지를 위한 **질의 불변성 검사(Query-Invariance Probing)** 프로토타입.

- 설계: [`docs/design.md`](docs/design.md)
- 작업 규칙(Claude Code용): [`CLAUDE.md`](CLAUDE.md)

## 시작하기
```bash
python3.8 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # API 키 입력
pytest
```

## 진행 단계
0. 파일럿 (`notebooks/pilot_variance_measurement.ipynb`) — 핵심 가정 검증, 통과 시에만 다음 단계
1. 실시간 파이프라인 구현 (`src/`)
2. 정적 평가 (`eval/run_eval.py`)
3. 적대적 강건성 평가 (선택)
