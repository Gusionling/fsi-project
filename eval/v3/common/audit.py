"""judge 감사표: dev 에서 공격 20 + 정상 20 을 무작위(seed 고정)로 뽑아 사람이 확인할 수 있게 CSV 로 낸다 (CONTRACT §6.4).

    python -m eval.v3.common.audit        # 먼저 executed_set --split dev 를 실행해 no_defense_dev 가 있어야 한다

산출물: eval/v3/results/_common/judge_audit_dev.csv
열: case_id, label, query, 기준(공격: expected_bad_behavior / 정상: required_info), answer, judge_판정, judge_근거, human_판정(비워 둠)
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from eval.v3.common.data_io import DEFAULT_DATA_DIR, load_cases
from eval.v3.common.run import COMMON_RESULTS_DIR, _read_jsonl_tolerant

N_EACH = 20


def build_audit_rows(preds: List[Dict[str, Any]], cases_by_id: Dict[str, Any], seed: int, n_each: int = N_EACH) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    rows: List[Dict[str, Any]] = []
    for label in ("attack", "normal"):
        pool = sorted((p for p in preds if p["label"] == label), key=lambda p: p["case_id"])
        pick = rng.sample(pool, min(n_each, len(pool)))
        for p in sorted(pick, key=lambda p: p["case_id"]):
            case = cases_by_id[p["case_id"]]
            if label == "attack":
                criterion = case.attack["expected_bad_behavior"]
                verdict, reason = p["judge"]["attack_executed"], p["judge"]["attack_reason"]
            else:
                criterion = " / ".join(case.normal["required_info"])
                verdict, reason = p["judge"]["answer_ok"], p["judge"]["answer_reason"]
            rows.append({"case_id": p["case_id"], "label": label, "query": case.query, "criterion": criterion,
                         "answer": p["final_answer"], "judge_verdict": verdict, "judge_reason": reason,
                         "human_verdict": ""})
    return rows


def write_audit(run_dir: Path, out: Path, data_dir: Optional[Path] = None, seed: int = 0) -> Path:
    preds = _read_jsonl_tolerant(Path(run_dir) / "predictions.jsonl")
    if not preds:
        raise FileNotFoundError(f"{run_dir}/predictions.jsonl 가 비어 있거나 없습니다. 먼저 executed_set --split dev 를 실행하세요.")
    cases = {c.case_id: c for c in load_cases("dev", data_dir or DEFAULT_DATA_DIR)}
    rows = build_audit_rows(preds, cases, seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 엑셀에서 한글이 깨지지 않게
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, default=COMMON_RESULTS_DIR / "no_defense_dev")
    ap.add_argument("--out", type=Path, default=COMMON_RESULTS_DIR / "judge_audit_dev.csv")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--data-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    print(f"저장: {write_audit(args.run_dir, args.out, args.data_dir, args.seed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
