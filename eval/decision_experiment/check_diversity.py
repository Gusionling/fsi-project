"""홀드아웃(및 필요 시 dev) 데이터셋의 중복/엔티티 다양성을 검사한다.

데이터 검사용 스크립트라 protocol-frozen-v1의 코드 동결 대상이 아니다(M0/B0/B1/B2/B3
점수 계산 로직을 건드리지 않는다). 규칙:
  - 그룹별 서로 다른 문장 수 >= 그룹 건수의 90%
  - 계좌/URL 엔티티가 등장하는 intent에서는, 그 intent 안의 서로 다른 엔티티 수 >= 3
위반이 있으면 에러 메시지를 출력하고 종료 코드 1로 끝낸다(CI/실행 전 게이트 용도).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from eval.decision_experiment.common import ACCOUNT_RE, URL_RE, free_text_of  # noqa: E402

HOLDOUT_DIR = ROOT / "eval" / "dataset" / "holdout"
TIER_FILES = ["t0.json", "t1.json", "t2.json", "t2p.json", "t3.json", "t4.json", "hard_negative.json"]

MIN_DISTINCT_RATIO = 0.9
MIN_ENTITIES_PER_INTENT = 3


def load_all():
    items = []
    for fname in TIER_FILES:
        path = HOLDOUT_DIR / fname
        if not path.exists():
            continue
        items.extend(json.loads(path.read_text(encoding="utf-8")))
    return items


def check(items: list[dict]) -> list[str]:
    errors = []

    by_group = defaultdict(list)
    for it in items:
        key = (it.get("tier"), it.get("group") or "normal")
        by_group[key].append(it)

    for (tier, group), g_items in sorted(by_group.items()):
        texts = [free_text_of(it["schema_type"], it["chunk"]) for it in g_items]
        distinct = len(set(texts))
        n = len(g_items)
        ratio = distinct / n if n else 1.0
        if ratio < MIN_DISTINCT_RATIO:
            errors.append(
                f"[{tier}/{group}] 서로 다른 문장 비율 {ratio:.0%} ({distinct}/{n}) "
                f"< {MIN_DISTINCT_RATIO:.0%}"
            )

    by_tier_intent = defaultdict(list)
    for it in items:
        if not it.get("intent"):
            continue
        by_tier_intent[(it["tier"], it["intent"])].append(it)

    for (tier, intent), ti_items in sorted(by_tier_intent.items()):
        entities = set()
        for it in ti_items:
            t = free_text_of(it["schema_type"], it["chunk"])
            entities.update(ACCOUNT_RE.findall(t))
            entities.update(URL_RE.findall(t))
        if entities and len(entities) < MIN_ENTITIES_PER_INTENT:
            errors.append(
                f"[{tier}/{intent}] 서로 다른 엔티티 {len(entities)}개 < {MIN_ENTITIES_PER_INTENT}개 "
                f"(엔티티: {sorted(entities)})"
            )

    return errors


def main() -> int:
    items = load_all()
    errors = check(items)
    if not errors:
        print(f"다양성 검사 통과: {len(items)}건, 위반 0건")
        return 0
    print(f"다양성 검사 실패: {len(errors)}건 위반")
    for e in errors:
        print(" -", e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
