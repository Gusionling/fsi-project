"""4. 이상행동 추출기 (실시간)."""
from typing import Optional


def extract_unexpected(response: str, query: str) -> Optional[str]:
    """질의와 무관한 민감정보/지시수행 span 을 반환하고, 없으면 None."""
    raise NotImplementedError
