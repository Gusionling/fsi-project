"""3. 질의 불변성 검사 엔진 (실시간, 핵심 모듈)."""
from typing import Any


def query_invariance_probe(chunk: str, probes: list[str]) -> dict[str, Any]:
    """{'invariance_score': float, 'hits': list, 'n_probes': int} 를 반환한다."""
    raise NotImplementedError
