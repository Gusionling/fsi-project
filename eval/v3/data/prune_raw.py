"""raw/ 의 기존 기반 문서 중 현재 검사(엄격한 엔티티 위생, 선택적으로 모델 QA)를 통과하지 못하는 것을 지운다 (소유자 data).
지운 sid 는 gen_bases.py 가 다시 만든다. test_sealed 는 sid 와 건수만 출력한다(내용은 출력하지 않음).

    python eval/v3/data/prune_raw.py [--qa] [--changed-rev2] [--stages ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import data_lib as D  # noqa: E402
from eval.v3.data import gen_lib as G  # noqa: E402

STAGES = ["attack_bases", "normal_dev", "normal_calib", "normal_test_sealed", "donors", "integrity"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", action="store_true", help="관련성·일관성 모델 점검까지 한다")
    ap.add_argument("--changed-rev2", action="store_true", help="rev2 로 시나리오가 바뀐 행의 기존 기록을 지운다")
    ap.add_argument("--stages", nargs="*", default=STAGES)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    reg = D.load_registry()
    llm = G.make_llm()
    changed = D.read_json(D.DATA_DIR / "prompts" / "rev2_changed.json") if args.changed_rev2 else {}
    for stage in args.stages:
        path = D.DATA_DIR / "raw" / f"{stage}.jsonl"
        if not path.exists():
            continue
        recs = D.read_jsonl(path)
        drop = {}
        rev2 = set(changed.get(stage.replace("normal_", ""), []))

        def check(rec):
            if rec["sid"] in rev2:
                return rec["sid"], "rev2"
            texts = [rec["query"], rec["target"]] + rec["contexts"]
            probs = G.pre_lint_pieces(texts, reg)
            if probs:
                return rec["sid"], "위생: " + probs[0][:40]
            if args.qa and stage not in ("donors", "integrity"):
                ok, why = G.qa_check(llm, rec)
                if not ok:
                    return rec["sid"], "qa: " + why[:60]
            return rec["sid"], None

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for sid, why in ex.map(check, recs):
                if why:
                    drop[sid] = why
        kept = [r for r in recs if r["sid"] not in drop]
        D.write_jsonl(path, kept)
        reasons = {}
        for w in drop.values():
            reasons[w.split(":")[0]] = reasons.get(w.split(":")[0], 0) + 1
        print(f"[{stage}] {len(recs)} → {len(kept)} (삭제 {len(drop)} {reasons})", ("sid " + str(sorted(drop)[:10])) if stage != "normal_test_sealed" and drop else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
