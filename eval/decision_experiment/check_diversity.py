"""홀드아웃(및 필요 시 dev) 데이터셋의 중복/엔티티 다양성을 검사한다.

데이터 검사용 스크립트라 protocol-frozen-v1의 코드 동결 대상이 아니다(M0/B0/B1/B2/B3
점수 계산 로직을 건드리지 않는다). 규칙:
  - 그룹별 서로 다른 문장 수 >= 그룹 건수의 90%
  - 계좌/URL 엔티티가 등장하는 intent에서는, 그 intent 안의 서로 다른 엔티티 수 >= 3
위반이 있으면 에러 메시지를 출력하고 종료 코드 1로 끝낸다(CI/실행 전 게이트 용도).

**알려진 예외(EXEMPT_GROUPS, `is_exempt_group()`)**: 아래 두 범위는 위반이 있어도 실패로
세지 않고 "면제됨"으로만 표시한다. 둘 다 "수정해 달라"는 요청을 받은 적이 없는 범위
밖(out-of-scope)/레거시 데이터다.
  - **tier 전체가 T2p**: `docs/decision_protocol.md` 1.5절/5절에 따라 T2p는 판정 규칙
    어디에도 쓰이지 않는 참고 전용 티어다(공격 유형 자체가 질의 불변성 검사의 설계 범위
    밖). 핵심 비교에 영향을 주지 않으므로 문장 다양성을 추가로 손보지 않았다.
  - **T4의 group명이 "b2_evasion"으로 시작하는 5개 하위 그룹**: B2(KAD)를 피하도록 설계된
    소규모(의도당 3건, 총 15건) 레거시 그룹으로, 체크포인트 1.5 이후 다른 T4 그룹
    (b0_evasion/b1_evasion)처럼 전수 재작성하는 작업을 거치지 않았다. `docs/decision_protocol.md`
    4절에 따라 B2에 대한 "맞춤 공격(targeted)" 모집단으로만 쓰이며, 다양성 부족이 recall
    계산 자체를 왜곡하지는 않는다(B2의 판정은 문장 내용이 아니라 canary 토큰 존재 여부이므로).
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

# tier/group이 아래 조건에 맞으면 문장-다양성 위반이 있어도 에러가 아니라 "면제됨"으로만
# 보고한다. 사유는 위 모듈 docstring 참고. T2p는 tier 전체(10개 하위 group), T4는 group명이
# "b2_evasion"으로 시작하는 5개 하위 group(의도별 b2_evasion_* 그룹)만 면제 대상이다 —
# b0_evasion_*/b1_evasion_* 그룹은 면제 대상이 아니다. intent 단위 엔티티 검사는 현재 두
# 면제 대상 모두 위반을 일으키지 않으므로 별도 처리하지 않는다.
def is_exempt_group(tier: str, group: str) -> bool:
    if tier == "T2p":
        return True
    if tier == "T4" and group.startswith("b2_evasion"):
        return True
    return False


def load_all():
    items = []
    for fname in TIER_FILES:
        path = HOLDOUT_DIR / fname
        if not path.exists():
            continue
        items.extend(json.loads(path.read_text(encoding="utf-8")))
    return items


def check(items: list[dict]) -> tuple[list[str], list[str]]:
    errors = []
    exempted = []

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
            msg = (
                f"[{tier}/{group}] 서로 다른 문장 비율 {ratio:.0%} ({distinct}/{n}) "
                f"< {MIN_DISTINCT_RATIO:.0%}"
            )
            if is_exempt_group(tier, group):
                exempted.append(msg)
            else:
                errors.append(msg)

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
            msg = (
                f"[{tier}/{intent}] 서로 다른 엔티티 {len(entities)}개 < {MIN_ENTITIES_PER_INTENT}개 "
                f"(엔티티: {sorted(entities)})"
            )
            if is_exempt_group(tier, intent):
                exempted.append(msg)
            else:
                errors.append(msg)

    return errors, exempted


def main() -> int:
    items = load_all()
    errors, exempted = check(items)
    if exempted:
        print(f"면제됨(EXEMPT_GROUPS, 실패로 세지 않음): {len(exempted)}건")
        for e in exempted:
            print(" -", e)
    if not errors:
        print(f"다양성 검사 통과: {len(items)}건, 위반 0건(면제 {len(exempted)}건 제외)")
        return 0
    print(f"다양성 검사 실패: {len(errors)}건 위반")
    for e in errors:
        print(" -", e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
