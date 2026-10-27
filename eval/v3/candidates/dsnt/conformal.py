"""Split conformal: 큰 s는 비적합, 작은 p는 의심. 동률은 >= 로 포함한다."""
import math
import warnings


class InsufficientCalibrationWarning(UserWarning):
    pass


def minimum_p(m: int) -> float:
    if m < 0:
        raise ValueError("m은 음수일 수 없습니다")
    return 1 / (m + 1)


def p_value(score: float, calibration: list[float]) -> float:
    if not all(math.isfinite(x) for x in [score, *calibration]):
        raise ValueError("conformal 점수는 유한해야 합니다")
    return (1 + sum(s >= score for s in calibration)) / (len(calibration) + 1)


def can_decide(m: int, alpha: float, *, warn: bool = True) -> bool:
    # alpha는 정상 오차 상한이다. 낮추면 덜 막고 높이면 더 막는다.
    if not 0 < alpha < 1:
        raise ValueError("alpha는 0과 1 사이여야 합니다")
    ready = m > 0 and minimum_p(m) <= alpha
    if not ready and warn:
        warnings.warn(f"DSNT 판정 보류: m={m}, 최소 p={minimum_p(m):.6g} > alpha={alpha} 또는 빈 보정 집합",
                      InsufficientCalibrationWarning, stacklevel=2)
    return ready
