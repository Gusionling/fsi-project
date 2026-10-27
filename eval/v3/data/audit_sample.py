"""무작위 30건 감사표 (소유자 data). seed 고정으로 dev·calib 케이스(sealed 제외)에서 30건을 뽑는다.

    python eval/v3/data/audit_sample.py --show 0-14     # 에이전트가 읽을 내용을 출력
    python eval/v3/data/audit_sample.py                 # prompts/audit_marks.json 의 판정을 합쳐 audit_sample.csv 작성

판정은 에이전트가 직접 읽고 prompts/audit_marks.json 에 적는다: {case_id: {label_ok, realistic, ambiguous, note}}.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import data_lib as D  # noqa: E402

SEED = 20261023
N = 30


def sample():
    pool = D.load_cases("dev") + D.load_cases("calib")
    pool.sort(key=lambda r: r["case_id"])
    rng = random.Random(SEED)
    return sorted(rng.sample(pool, N), key=lambda r: r["case_id"])


def describe(r) -> str:
    a = r.get("attack") or {}
    tag = f'{r["label"]}' + (f' {a["tier"]}/{a["intent"]}' if a else "") + (f' hn={r["normal"]["hard_negative_type"]}' if r["label"] == "normal" else "") \
        + (f' {r["integrity"]["field"]}' if r["label"] == "integrity" else "")
    lines = [f'## {r["case_id"]} [{r["split"]}] {tag}', f'Q: {r["query"]}']
    for c in r["chunks"]:
        lines.append(f'  [{c["role"]}] {c["text"][:430]}'.replace("\n", " / "))
    if a:
        lines.append(f'  EXPECT: {a["expected_bad_behavior"]} | ents={a.get("attacker_entities")} | trig={a.get("trigger_condition")} | twin={a.get("clean_twin_case_id")}')
        if r.get("trusted_fixture"):
            lines.append(f'  FIXTURE: {r["trusted_fixture"]}')
    elif r["label"] == "normal":
        lines.append(f'  REQUIRED: {r["normal"]["required_info"]} | FIXTURE: {r.get("trusted_fixture")}')
    else:
        lines.append(f'  INTEGRITY: {r["integrity"]}')
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", default=None, help="예: 0-14")
    args = ap.parse_args()
    rows = sample()
    if args.show:
        lo, hi = (int(x) for x in args.show.split("-"))
        for r in rows[lo:hi + 1]:
            print(describe(r))
        return 0
    marks = D.read_json(D.DATA_DIR / "prompts" / "audit_marks.json")
    out = D.DATA_DIR / "audit_sample.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "split", "label", "tier_or_hn", "intent", "query", "label_ok", "realistic", "ambiguous", "note"])
        for r in rows:
            m = marks[r["case_id"]]
            a = r.get("attack") or {}
            w.writerow([r["case_id"], r["split"], r["label"], a.get("tier") or (r.get("normal") or {}).get("hard_negative_type", ""),
                        a.get("intent", ""), r["query"], m["label_ok"], m["realistic"], m["ambiguous"], m["note"]])
    print(f"저장: {out} ({len(rows)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
