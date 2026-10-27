"""기반 문서 생성 (소유자 data). 시나리오 표(prompts/scenarios_*.json)의 각 행을 OpenAI 모델로 쓴다.

    python eval/v3/data/gen_bases.py --stage attack_bases|normal_dev|normal_calib|normal_test_sealed|donors|integrity [--workers 8]

결과는 raw/<stage>.jsonl 에 행마다 바로 기록되고(이어쓰기 가능), 모델명은 author_model 로 이어진다.
정상 문서와 donor 는 전부 한 중복 색인에 들어가므로 split·donor 사이에도 근접 중복이 생기지 않는다.
test_sealed 단계는 건수·분포만 출력한다(내용은 출력하지 않는다).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import data_lib as D  # noqa: E402
from eval.v3.data import gen_lib as G  # noqa: E402

RAW = D.DATA_DIR / "raw"
STAGES = ["attack_bases", "normal_dev", "normal_calib", "normal_test_sealed", "donors", "integrity"]
MAX_ROUNDS = 6


def load_rows(stage: str) -> List[Dict[str, Any]]:
    p = D.DATA_DIR / "prompts"
    if stage == "attack_bases":
        return [dict(r["base"], sid=r["aid"] + "_base") for r in D.read_json(p / "scenarios_attack_bases.json")]
    if stage.startswith("normal_"):
        return D.read_json(p / "scenarios_normal.json")[stage[len("normal_"):]]
    if stage == "donors":
        return [dict(r, donor=True) for r in D.read_json(p / "scenarios_donors.json")]
    return D.read_json(p / "scenarios_integrity.json")


def build_index(skip_stage: str) -> G.DupIndex:
    """이미 만들어 둔 다른 단계의 모든 텍스트를 중복 색인에 넣는다."""
    idx = G.DupIndex()
    for stage in STAGES:
        path = RAW / f"{stage}.jsonl"
        if stage == skip_stage or not path.exists():
            continue
        for rec in D.read_jsonl(path):
            for k, t in enumerate([rec["target"]] + rec["contexts"]):
                idx.add(f"{rec['sid']}#{k}", t)
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=STAGES)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--start-round", type=int, default=0, help="이미 시도한 프롬프트와 다른 변형을 쓰려면 올린다")
    args = ap.parse_args()
    stage = args.stage
    RAW.mkdir(exist_ok=True)
    registry = D.load_registry()
    llm = G.make_llm()
    rows = load_rows(stage)[: args.limit]
    path = RAW / f"{stage}.jsonl"
    done = {r["sid"]: r for r in D.read_jsonl(path)} if path.exists() else {}
    idx = build_index(stage)
    first6 = set()
    for other in STAGES:
        op = RAW / f"{other}.jsonl"
        if op.exists() and other != "donors":
            first6.update(D.first_words(r["target"]) for r in D.read_jsonl(op))
    for rec in done.values():
        for k, t in enumerate([rec["target"]] + rec["contexts"]):
            idx.add(f"{rec['sid']}#{k}", t)
    pending = [r for r in rows if r["sid"] not in done]
    print(f"[{stage}] 행 {len(rows)}, 완료 {len(done)}, 남음 {len(pending)}")
    fn = G.candidate_integrity if stage == "integrity" else G.candidate
    t0 = time.time()
    reasons: Dict[str, int] = {}
    for rnd in range(MAX_ROUNDS):
        if not pending:
            break
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            results = list(ex.map(lambda r: fn(llm, r, registry, rnd + args.start_round), pending))
        nxt = []
        for row, (obj, why) in zip(pending, results):
            if obj is None:
                reasons[why[:30]] = reasons.get(why[:30], 0) + 1
                nxt.append(row)
                continue
            texts = [obj["target"]] + obj["contexts"]
            f6 = D.first_words(obj["target"])
            dup = next((idx.check(t) for t in texts if idx.check(t)), None)
            if (stage != "donors" and f6 in first6) or dup:
                reasons["중복/첫어절"] = reasons.get("중복/첫어절", 0) + 1
                nxt.append(row)
                continue
            for k, t in enumerate(texts):
                idx.add(f"{row['sid']}#{k}", t)
            first6.add(f6)
            rec = {"sid": row["sid"], "model": G.GEN_MODEL, "tries": rnd + 1, "row": row, **obj}
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done[row["sid"]] = rec
        print(f"  라운드 {rnd + 1}: 수락 {len(pending) - len(nxt)}, 재시도 {len(nxt)} ({time.time() - t0:.0f}s)")
        pending = nxt
    if pending:
        print(f"  [경고] 끝내 만들지 못한 행 {len(pending)}: {[r['sid'] for r in pending][:8]}")
    if reasons:
        print("  거절 사유:", dict(sorted(reasons.items(), key=lambda x: -x[1])[:6]))
    print(f"[{stage}] 총 {len(done)}/{len(rows)}  LLM 호출 {llm.summary()['logical']} (실제 {llm.summary()['api']})")
    return 0 if not pending else 1


if __name__ == "__main__":
    sys.exit(main())
