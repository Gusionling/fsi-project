"""raw/ 와 공격 문구를 합쳐 최종 JSONL 을 만든다 (소유자 data).

    python eval/v3/data/assemble.py

만드는 것: cases_dev.jsonl (공격 250 + 짝 정상 + 독립 정상 + 무결성 60), cases_calib.jsonl, cases_test_sealed.jsonl, donors.jsonl,
          sealed_manifest.json (sealed 의 건수·분포·크기·해시 — sealed 내용은 출력하지 않는다)
같은 입력이면 같은 출력이다(정렬·시드 고정). 생성 직후 lint 를 메모리에서 돌려 manifest 에 결과를 남긴다.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import assemble_lib as A  # noqa: E402
from eval.v3.data import data_lib as D  # noqa: E402
from eval.v3.data import gen_lib as G  # noqa: E402
from eval.v3.data import lint_data as L  # noqa: E402

TODAY = "2026-10-23"
P = D.DATA_DIR / "prompts"
RAW = D.DATA_DIR / "raw"


def chunks_of(case_id: str, rec: Dict[str, Any], target_text: str) -> List[Dict[str, Any]]:
    row = rec["row"]
    out = [{"chunk_id": f"{case_id}_t", "text": target_text, "role": "target", "source_type": A.source_type_of(row["doc_type"])}]
    for i, c in enumerate(rec["contexts"], 1):
        out.append({"chunk_id": f"{case_id}_c{i}", "text": c, "role": "context", "source_type": "unknown"})
    return out


def fixture_of(row: Dict[str, Any]) -> Dict[str, Any]:
    if row.get("status_key") and row.get("status_state"):
        return {"application_status": {row["status_key"]: row["status_state"]}}
    return {}


def normal_case(case_id: str, split: str, rec: Dict[str, Any], generator: str, status_key=None, status_state=None) -> Dict[str, Any]:
    row = rec["row"]
    row = dict(row, status_key=status_key or row.get("status_key"), status_state=status_state or row.get("status_state"))
    out = {
        "case_id": case_id, "split": split, "label": "normal", "query": rec["query"], "topic": row["topic"],
        "chunks": chunks_of(case_id, rec, rec["target"]),
        "normal": {"hard_negative_type": row["hn_type"], "gold_facts": rec["gold_facts"], "required_info": rec["required_info"]},
        "author_model": rec["model"], "generator": generator, "created_at": TODAY,
    }
    fx = fixture_of(row)
    if fx:
        out["trusted_fixture"] = fx
    return out


def build_dev_attacks(specs, raw_bases, hand, llm_cl, final_probe, attempts, relabel=None):
    relabel = relabel or {}
    attacks, twins = [], []
    for s in specs:
        aid = s["aid"]
        rec = raw_bases[aid + "_base"]
        cl = hand.get(aid) or llm_cl[aid]
        is_hand = aid in hand
        author = D.HAND_AUTHOR if is_hand else llm_cl[aid]["model"]
        target = A.build_target(s, rec["target"], cl["clause"])
        a: Dict[str, Any] = {"tier": s["tier"], "intent": s["intent"], "has_entity": s["intent"] in D.ENTITY_INTENTS,
                             "expected_bad_behavior": cl["behavior"].replace("{E}", s["attacker_entity"] or "공격자 엔티티")}
        if a["has_entity"]:
            a["attacker_entities"] = [s["attacker_entity"]]
        trig = cl.get("trigger") if isinstance(cl, dict) else None
        if s["tier"] in ("T1", "T3") and trig:
            a["trigger_condition"] = trig
        twin_id = f"nor_twin_{aid[4:]}" if s["twin"] else None
        if twin_id:
            a["clean_twin_case_id"] = twin_id
        notes = f"기반 문서: {rec['model']}; 공격 문구 작성: {author} ({'직접' if is_hand else '모델'})."
        if s["tier"] == "T4":
            fp = final_probe[aid]
            notes += (f" T4 탐지기 시험(통과=B0<2·B1<70): B0={fp['b0']}, B1={fp['b1']}, 문구 시도 {fp['attempts']}회, "
                      f"{'통과' if fp['pass'] else '못 피함(최대 3회 시도 후에도 탐지됨 — 버리지 않고 남김)'}.")
        case = {"case_id": aid, "split": "dev", "label": "attack", "query": rec["query"], "topic": s["topic"],
                "chunks": chunks_of(aid, rec, target), "attack": a, "author_model": author,
                "generator": f"build_scenarios.py#{aid}; gen_bases.py --stage attack_bases; prompts/{'hand' if is_hand else 'llm'}_clauses.json#{aid}",
                "created_at": TODAY, "notes": notes}
        if s["intent"] == "false_confirmation":
            case["trusted_fixture"] = {"application_status": {s["status_key"]: s["status_state"]}}
        attacks.append(case)
        if twin_id:
            twin = normal_case(twin_id, "dev", dict(rec, row=dict(rec["row"], status_key=s["status_key"], status_state=s["status_state"],
                                                                  hn_type=relabel.get(rec["sid"], rec["row"]["hn_type"]))),
                               f"clean twin of {aid}; gen_bases.py --stage attack_bases; {rec['model']}")
            twins.append(twin)
    return attacks, twins


def main() -> int:
    specs = D.read_json(P / "scenarios_attack_bases.json")
    raw_bases = {r["sid"]: r for r in D.read_jsonl(RAW / "attack_bases.jsonl")}
    hand = D.read_json(P / "hand_clauses.json")
    llm_cl = D.read_json(P / "llm_clauses.json")
    final_probe = D.read_json(P / "t4_final_probe.json")
    missing = [s["aid"] for s in specs if s["aid"] + "_base" not in raw_bases or (s["aid"] not in hand and s["aid"] not in llm_cl)]
    if missing:
        print("공격 문구/기반 문서가 없는 행:", missing)
        return 1
    relabel_path = P / "hn_relabel.json"
    relabel = D.read_json(relabel_path) if relabel_path.exists() else {}
    attacks, twins = build_dev_attacks(specs, raw_bases, hand, llm_cl, final_probe, None, relabel)

    dev_indep = [normal_case(r["sid"], "dev", r, f"scenarios_normal.json#{r['sid']}; gen_bases.py --stage normal_dev; {r['model']}")
                 for r in D.read_jsonl(RAW / "normal_dev.jsonl")]
    integ = []
    for r in D.read_jsonl(RAW / "integrity.jsonl"):
        row = r["row"]
        integ.append({"case_id": row["sid"], "split": "dev", "label": "integrity", "query": r["query"], "topic": row["topic"],
                      "chunks": chunks_of(row["sid"], r, r["target"]),
                      "integrity": {"field": row["field"], "poisoned_value": row["poisoned_value"], "true_value": row["true_value"]},
                      "author_model": r["model"], "generator": f"scenarios_integrity.json#{row['sid']}; gen_bases.py --stage integrity; {r['model']}",
                      "created_at": TODAY,
                      "notes": "올바른 값이 context 에 있음" if row["with_truth"] else "올바른 값이 문서 어디에도 없음"})
    dev = sorted(attacks + twins + dev_indep + integ, key=lambda r: r["case_id"])

    def split_cases(split: str, stage: str) -> List[Dict[str, Any]]:
        return sorted((normal_case(r["sid"], split, r, f"scenarios_normal.json#{r['sid']}; gen_bases.py --stage {stage}; {r['model']}")
                       for r in D.read_jsonl(RAW / f"{stage}.jsonl")), key=lambda r: r["case_id"])

    calib = split_cases("calib", "normal_calib")
    sealed = split_cases("test_sealed", "normal_test_sealed")

    donors = []
    for r in D.read_jsonl(RAW / "donors.jsonl"):
        row = r["row"]
        for k, text in enumerate([r["target"]] + r["contexts"]):
            donors.append({"chunk_id": f"{row['sid']}_{k}", "topic": row["topic"], "text": text, "split": row["split"],
                           "source_type": A.source_type_of(row["doc_type"]) if k == 0 else "unknown",
                           "hard_negative_type": row["hn_type"], "author_model": r["model"]})
    donors.sort(key=lambda d: d["chunk_id"])

    D.write_jsonl(D.DATA_DIR / D.CASE_FILES["dev"], dev)
    D.write_jsonl(D.DATA_DIR / D.CASE_FILES["calib"], calib)
    D.write_jsonl(D.DATA_DIR / D.CASE_FILES["test_sealed"], sealed)
    D.write_jsonl(D.DATA_DIR / D.DONORS_FILE, donors)

    findings, stats = L.lint_dataset({"dev": dev, "calib": calib, "test_sealed": sealed}, donors, D.load_registry(), D.load_topics())
    sealed_path = D.DATA_DIR / D.CASE_FILES["test_sealed"]
    hn = Counter(r["normal"]["hard_negative_type"] for r in sealed)
    D.write_json(D.DATA_DIR / D.SEALED_MANIFEST, {
        "n": len(sealed), "labels": dict(Counter(r["label"] for r in sealed)), "hn": dict(hn), "size_bytes": sealed_path.stat().st_size,
        "sha256": D.file_sha256(sealed_path), "topics": dict(Counter(r["topic"] for r in sealed)),
        "status_fixture_cases": sum(bool(r.get("trusted_fixture")) for r in sealed),
        "lint_passed_at_generation": not findings.errors, "lint_errors_at_generation": len(findings.errors),
        "note": "sealed 내용은 보고서·채팅에 인용하지 않는다. 이 파일에는 건수와 분포만 있다."})

    print(f"dev {len(dev)} (공격 {len(attacks)}, 짝 정상 {len(twins)}, 독립 정상 {len(dev_indep)}, 무결성 {len(integ)}), calib {len(calib)}, sealed {len(sealed)}, donors {len(donors)}")
    counts = Counter((lvl, chk) for lvl, chk, _ in findings.items)
    for (lvl, chk), n in sorted(counts.items()):
        print(f"  [{lvl}] {chk}: {n}건")
    shown = Counter()
    for lvl, chk, msg in findings.items:
        if "nor_sealed" in msg:
            print(f"    - {chk}: (sealed) {msg.split(':')[0]}")  # 내용은 출력하지 않고 case_id 만 보여 준다
            continue
        if shown[chk] < 4:
            print(f"    - {chk}: {msg[:230]}")
            shown[chk] += 1
    print("stats:", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
