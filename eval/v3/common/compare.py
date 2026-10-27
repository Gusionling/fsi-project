"""두 run 을 같은 executed set E 위에서 비교한다 (paired bootstrap 95%, B=10,000, seed 고정).

    python -m eval.v3.common.compare --a <run_dir> --b <run_dir> [--metric executed_recall|asr_after|fpr|answer_acc]

차이는 항상 (a - b) 이다.
  executed_recall: 양수 = a 가 더 많이 개입      asr_after: 음수 = a 가 공격이 덜 실행됨 (더 좋음)
  fpr:             음수 = a 의 오탐이 더 적음     answer_acc: 양수 = a 의 정상 답변 정확도가 더 높음
executed_recall / asr_after 는 E 위에서, fpr / answer_acc 는 두 run 에 공통인 정상 케이스 위에서 계산한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from eval.v3.common import metrics as M
from eval.v3.common.run import COMMON_RESULTS_DIR, _clean, _read_jsonl_tolerant, load_executed_ids

METRICS = ("executed_recall", "asr_after", "fpr", "answer_acc")


def _load_run(run_dir: Path) -> Dict[str, Any]:
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    preds = {p["case_id"]: p for p in _read_jsonl_tolerant(run_dir / "predictions.jsonl")}
    return {"meta": meta, "preds": preds}


def compare_runs(
    run_a: Path,
    run_b: Path,
    metrics: Sequence[str] = METRICS,
    *,
    executed_file: Optional[Path] = None,
    n_boot: int = 10_000,
    seed: int = 0,
) -> Dict[str, Any]:
    a, b = _load_run(Path(run_a)), _load_run(Path(run_b))
    split = a["meta"]["split"]
    if b["meta"]["split"] != split:
        raise ValueError(f"split 이 다릅니다: {split} vs {b['meta']['split']}")
    if a["meta"]["split_sha256"] != b["meta"]["split_sha256"]:
        raise ValueError("두 run 의 split 파일 sha256 이 다릅니다 (다른 데이터로 돌린 결과는 비교할 수 없습니다).")

    executed_file = Path(executed_file) if executed_file else COMMON_RESULTS_DIR / f"executed_{split}.json"
    E = load_executed_ids(executed_file, split, a["meta"]["split_sha256"])
    out: Dict[str, Any] = {"a": a["meta"]["defense"], "b": b["meta"]["defense"], "split": split, "diff": "a - b",
                           "metrics": {}}

    normals = sorted(c for c, p in a["preds"].items() if p["label"] == "normal" and c in b["preds"])
    for m in metrics:
        if m in ("executed_recall", "asr_after"):
            if E is None:
                raise FileNotFoundError(f"{executed_file} 가 없습니다. 먼저 executed_set 을 실행하세요.")
            ids = E["case_ids"]
            missing = [c for c in ids if c not in a["preds"] or c not in b["preds"]]
            if missing:
                raise ValueError(f"{m}: E 중 {len(missing)}건이 한쪽 run 에 없습니다 (예: {missing[:3]}).")
            if m == "executed_recall":
                va = [float(a["preds"][c]["intervened"]) for c in ids]
                vb = [float(b["preds"][c]["intervened"]) for c in ids]
            else:
                va = [float(a["preds"][c]["judge"]["attack_executed"]) for c in ids]
                vb = [float(b["preds"][c]["judge"]["attack_executed"]) for c in ids]
            n_pop = len(ids)
        else:
            if m == "fpr":
                va = [float(a["preds"][c]["intervened"]) for c in normals]
                vb = [float(b["preds"][c]["intervened"]) for c in normals]
            else:
                va = [float(a["preds"][c]["judge"]["answer_ok"]) for c in normals]
                vb = [float(b["preds"][c]["judge"]["answer_ok"]) for c in normals]
            n_pop = len(normals)
        res = M.paired_bootstrap(va, vb, n_boot=n_boot, seed=seed)
        res.update(rate_a=(sum(va) / n_pop) if n_pop else None, rate_b=(sum(vb) / n_pop) if n_pop else None,
                   population="executed set E" if m in ("executed_recall", "asr_after") else "공통 정상 케이스")
        out["metrics"][m] = res
    return _clean(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, type=Path)
    ap.add_argument("--b", required=True, type=Path)
    ap.add_argument("--metric", choices=METRICS, action="append", default=None)
    ap.add_argument("--executed-file", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None, help="결과 JSON 저장 경로(선택)")
    args = ap.parse_args(argv)
    res = compare_runs(args.a, args.b, args.metric or METRICS, executed_file=args.executed_file, seed=args.seed)
    text = json.dumps(res, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
