"""전체 파이프라인 조립: 1(사전필터) → 2(decoy) → 3(불변성 검사) → 4(추출) → 5(판정) → 6(Spotlighting)."""
from typing import Any


def run_pipeline(user_query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    raise NotImplementedError
