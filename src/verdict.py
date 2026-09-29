"""5. 판정 로직 (실시간)."""

DEFAULT_THRESHOLD = 0.5  # 0단계 파일럿/2단계 ROC 로 재보정 예정


def repeated_overlap_ratio(unexpected: list[str | None]) -> float:
    raise NotImplementedError


def decide(invariance_score: float, threshold: float = DEFAULT_THRESHOLD) -> str:
    """'pass' 또는 'block'."""
    raise NotImplementedError
