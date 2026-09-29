"""2. Decoy 질의뱅크 생성기 (실시간, 핵심검사 직전)."""


def build_probe_set(chunk_topic_hint: str, n: int = 4) -> list[str]:
    """chunk_topic_hint 는 스키마 메타데이터에서만 가져온다(청크 내용 금지)."""
    raise NotImplementedError
