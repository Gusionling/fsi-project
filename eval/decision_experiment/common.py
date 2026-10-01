"""결정 실험(M0 vs B0/B1/B2/B3) 공통 유틸리티.

dev set(파일럿 142건) 로드, 정규화 정규식(docs/decision_protocol.md와 동일), Wilson 신뢰구간.
src/의 기존 모듈은 건드리지 않고 src.llm만 그대로 재사용한다.
"""
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_REGISTRY = json.loads((ROOT / "config" / "schema_registry.json").read_text(encoding="utf-8"))

# --- docs/decision_protocol.md 1번 항목(M0 점수 정의)과 동일 ---
URL_RE = re.compile(r"https?://[^\s)\]]+")
ACCOUNT_RE = re.compile(r"\d{3,4}-\d{2,4}-\d{6,9}")
PHONE_RE = re.compile(r"\b\d{3,4}-\d{4}\b")


def normalize_core(text: str):
    if not text:
        return None
    m = URL_RE.search(text)
    if m:
        return ("url", m.group(0))
    m = ACCOUNT_RE.search(text)
    if m:
        return ("account", m.group(0))
    m = PHONE_RE.search(text)
    if m:
        return ("phone", m.group(0))
    return None


def free_text_of(schema_type: str, chunk: dict) -> str:
    fields = SCHEMA_REGISTRY[schema_type]["fields"]
    return " ".join(str(chunk[f]) for f, spec in fields.items() if spec.get("free_text") and f in chunk)


def load_dev_set() -> list[dict]:
    """파일럿 142건을 하나의 리스트로 합친다(정상 90[hard negative 15 포함] + naive 32 + optimized 20)."""
    pilot_dir = ROOT / "eval" / "dataset" / "pilot"
    p1_normal = json.loads((pilot_dir / "pilot1_normal.json").read_text(encoding="utf-8"))
    p1_injection = json.loads((pilot_dir / "pilot1_injection.json").read_text(encoding="utf-8"))
    p2 = json.loads((pilot_dir / "pilot2_boilerplate.json").read_text(encoding="utf-8"))
    p3 = json.loads((pilot_dir / "pilot3_pairs.json").read_text(encoding="utf-8"))
    items = p1_normal + p1_injection + p2 + p3
    for item in items:
        item.setdefault("hard_negative", False)
    assert len(items) == 142, f"dev set 개수 불일치: {len(items)}"
    return items


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval. (point_estimate, lower, upper) 반환. n=0이면 전부 nan."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def auc(scores_labels: list[tuple[float, int]]) -> float:
    """scores_labels: [(score, label)], label 1=positive(injection), 0=negative(normal).
    Mann-Whitney U 기반 AUC (rank 동점 처리 포함)."""
    pos = [s for s, y in scores_labels if y == 1]
    neg = [s for s, y in scores_labels if y == 0]
    if not pos or not neg:
        return float("nan")
    count = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                count += 1.0
            elif p == n:
                count += 0.5
    return count / (len(pos) * len(neg))
