"""1. 스키마 사전필터 (실시간 1번째) — docs/design.md '스키마 사전필터' 참고."""
from typing import Any


def schema_prefilter(chunk: dict[str, Any], schema_type: str) -> str:
    """'pass' 또는 'suspect' 를 반환한다. suspect 만 핵심검사로 넘어간다."""
    raise NotImplementedError
