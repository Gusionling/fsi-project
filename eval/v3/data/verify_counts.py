"""CONTRACT §5.2 대비 현황표 (소유자 data). 모자라면 종료 코드 1.

    python eval/v3/data/verify_counts.py

test_sealed 는 V3_ALLOW_SEALED=1 이 아니면 열지 않고 sealed_manifest.json(건수·분포·파일 크기)만 본다.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import data_lib as D  # noqa: E402

TARGET = {"T1": 30, "T2": 90, "T3": 40, "T4": 90}
MIN_INTENT_PER_TIER = 10          # T2·T4 각각 5개 의도 모두 ≥ 10
MIN_NO_ENTITY_SHARE = 0.45        # T2·T4 의 엔티티 없는 의도 비율
DEV_NORMAL, CALIB_NORMAL, SEALED_NORMAL = 200, 200, 400
HN_MIN = {"dev": 12, "calib": 12, "test_sealed": 25}
DEV_HN_TOTAL = 100
INTEGRITY_EACH = 20
DONOR_MIN = 15
HAND_SHARE_MIN = 0.40             # T2·T4 에서 직접 쓴 항목 비율
TWIN_SHARE_MIN = 0.50


def sealed_summary(data_dir: Path) -> Optional[Dict[str, Any]]:
    """sealed 의 건수·hard negative 분포. 열 수 있으면 파일에서, 아니면 manifest 에서."""
    if D.sealed_open() and (data_dir / D.CASE_FILES["test_sealed"]).exists():
        rows = D.load_cases("test_sealed", data_dir)
        hn = Counter(r["normal"]["hard_negative_type"] for r in rows if r["label"] == "normal")
        return {"n": len(rows), "labels": dict(Counter(r["label"] for r in rows)), "hn": dict(hn), "source": "file"}
    manifest = data_dir / D.SEALED_MANIFEST
    if manifest.exists():
        m = D.read_json(manifest)
        path = data_dir / D.CASE_FILES["test_sealed"]
        if not path.exists() or path.stat().st_size != m.get("size_bytes"):
            return {"n": 0, "labels": {}, "hn": {}, "source": "manifest-불일치(파일 크기가 다름)"}
        return {"n": m["n"], "labels": m.get("labels", {}), "hn": m.get("hn", {}), "source": "manifest"}
    return None


class Report:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str, bool]] = []

    def add(self, name: str, need: str, have: str, ok: bool) -> None:
        self.rows.append((name, need, have, ok))

    def ge(self, name: str, have: float, need: float, fmt: Callable[[float], str] = lambda x: str(x)) -> None:
        self.add(name, f"≥ {fmt(need)}", fmt(have), have >= need)

    @property
    def ok(self) -> bool:
        return all(r[3] for r in self.rows)

    def print(self) -> bool:
        w = max(len(r[0]) for r in self.rows)
        for name, need, have, ok in self.rows:
            print(f"  {'OK  ' if ok else 'FAIL'} {name:<{w}}  필요 {need:<9} 현재 {have}")
        return all(r[3] for r in self.rows)


def check(data_dir: Path) -> "Report":
    rep = Report()
    pct = lambda x: f"{x:.0%}"  # noqa: E731

    topics, reg, procs = D.load_topics(data_dir), D.load_registry(data_dir), D.load_procedures(data_dir)
    rep.ge("topics", len(topics), 12)
    rep.ge("topic 별 질문 유형(최소)", min(len(t["question_types"]) for t in topics), 3)
    rep.ge("registry 계좌", len(reg["accounts"]), 8)
    rep.ge("registry URL", len(reg["urls"]), 8)
    rep.ge("registry 전화", len(reg["phones"]), 6)
    rep.ge("공식 절차", len(procs), 25)
    rep.add("절차 channel", "app/branch/ars/official_site", "ok",
            all(p["channel"] in {"app", "branch", "ars", "official_site"} for p in procs))

    dev, calib = D.load_cases("dev", data_dir), D.load_cases("calib", data_dir)
    attacks = [r for r in dev if r["label"] == "attack"]
    by_tier: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TARGET}
    for r in attacks:
        by_tier[r["attack"]["tier"]].append(r)
    for tier, need in TARGET.items():
        rep.ge(f"dev 공격 {tier}", len(by_tier[tier]), need)
    rep.ge("dev 공격 합계", len(attacks), sum(TARGET.values()))
    for tier in ("T2", "T4"):
        rows = by_tier[tier]
        intents = Counter(r["attack"]["intent"] for r in rows)
        for it in D.INTENTS:
            rep.ge(f"dev {tier} 의도 {it}", intents[it], MIN_INTENT_PER_TIER)
        share = sum(intents[i] for i in D.NO_ENTITY_INTENTS) / len(rows) if rows else 0.0
        rep.add(f"dev {tier} 엔티티 없는 의도 비율", f"≥ {MIN_NO_ENTITY_SHARE:.0%}", pct(share), share >= MIN_NO_ENTITY_SHARE)
        hand = sum(r["author_model"] in D.HAND_AUTHORS for r in rows) / len(rows) if rows else 0.0
        rep.add(f"dev {tier} 직접 쓴 비율", f"≥ {HAND_SHARE_MIN:.0%}", pct(hand), hand >= HAND_SHARE_MIN)
    twins = sum(1 for r in attacks if r["attack"].get("clean_twin_case_id"))
    share = twins / len(attacks) if attacks else 0.0
    rep.add("dev 공격 중 짝 케이스 비율", f"≥ {TWIN_SHARE_MIN:.0%}", pct(share), share >= TWIN_SHARE_MIN)
    rep.add("T3 trigger_condition", "전부", f"{sum(bool(r['attack'].get('trigger_condition')) for r in by_tier['T3'])}/{len(by_tier['T3'])}",
            all(r["attack"].get("trigger_condition") for r in by_tier["T3"]))

    integ = [r for r in dev if r["label"] == "integrity"]
    rep.ge("dev 무결성 합계", len(integ), 3 * INTEGRITY_EACH)
    fields = Counter(r["integrity"]["field"] for r in integ)
    for fld in ("fee", "deadline", "limit"):
        rep.ge(f"dev 무결성 {fld}", fields[fld], INTEGRITY_EACH)

    def normal_block(name: str, rows: List[Dict[str, Any]], need_n: int, hn_each: int, hn_total: Optional[int]) -> None:
        normals = [r for r in rows if r["label"] == "normal"]
        rep.ge(f"{name} 정상", len(normals), need_n)
        hn = Counter(r["normal"]["hard_negative_type"] for r in normals)
        for t in D.HN_TYPES:
            rep.ge(f"{name} hard negative {t}", hn[t], hn_each)
        if hn_total:
            rep.ge(f"{name} hard negative 합계", sum(hn[t] for t in D.HN_TYPES), hn_total)

    normal_block("dev", dev, DEV_NORMAL, HN_MIN["dev"], DEV_HN_TOTAL)
    normal_block("calib", calib, CALIB_NORMAL, HN_MIN["calib"], DEV_HN_TOTAL)
    sealed = sealed_summary(data_dir)
    if sealed is None:
        rep.add("test_sealed 정상", f"≥ {SEALED_NORMAL}", "파일/manifest 없음", False)
    else:
        rep.add(f"test_sealed 정상 ({sealed['source']})", f"≥ {SEALED_NORMAL}", str(sealed["labels"].get("normal", sealed["n"])),
                sealed["labels"].get("normal", sealed["n"]) >= SEALED_NORMAL)
        for t in D.HN_TYPES:
            rep.ge(f"test_sealed hard negative {t}", sealed["hn"].get(t, 0), HN_MIN["test_sealed"])

    donors = D.load_donors(data_dir)
    cnt = Counter((d["split"], d["topic"]) for d in donors)
    for split in ("dev", "calib"):
        low = [(t["topic"], cnt[(split, t["topic"])]) for t in topics if cnt[(split, t["topic"])] < DONOR_MIN]
        rep.add(f"donors {split} (topic 별 ≥ {DONOR_MIN})", "모든 topic", "ok" if not low else f"부족 {low[:3]}…", not low)

    rep.authors = Counter(r["author_model"] for r in dev + calib)  # type: ignore[attr-defined]
    return rep


def main() -> int:
    rep = check(D.DATA_DIR)
    print("CONTRACT §5.2 대비 현황")
    ok = rep.print()
    print(f"\nauthor_model 분포(dev+calib 케이스): {dict(rep.authors)}")  # type: ignore[attr-defined]
    print("\nVERIFY OK" if ok else "\nVERIFY FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
