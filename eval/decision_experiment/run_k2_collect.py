"""K2(청크 폭파) B팔 — 챗봇 응답 수집 전용(판정 없음).

docs/decision_protocol_v2.md §11(2026-10-06 사전 등록) 커밋 이후에만 실행한다.
공격210 + 정상130(dev90+dev2 hard_negative40) + 정책인접40 = 380청크에,
intent-blind 스키마-only 질의 풀에서 청크·시드별로 K=5개를 뽑아 챗봇 응답을 받는다.

판정(C' 적용)은 하지 않는다 — 응답은 logs/e1_responses_B_seed{N}.json에 그대로
캐시하고, 판정은 별도 단계(§11.4, 이 스크립트 다음)에서 분리해서 한다.

independent_generated*/human_written* 내용은 열지 않는다(대상에 포함하지 않는다).

실행: LLM_MAX_CALLS=20000 python -m eval.decision_experiment.run_k2_collect
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

os.environ.pop("LLM_OFFLINE", None)
from src import llm  # noqa: E402

llm.CACHE_DIR = ROOT / "eval" / "decision_experiment" / ".llm_cache_k2"

from eval.decision_experiment.k2_query_gen import build_query_pool, sample_queries_for_chunk, leakage_rate  # noqa: E402
from eval.decision_experiment.executed_verification import call_chatbot  # noqa: E402

K = 5
SEEDS = [42, 43, 44]


def load_target_380():
    """공격210 + 정상130 + 정책인접40. independent_generated*/human_written*는 포함하지 않는다."""
    holdout_dir = ROOT / "eval" / "dataset" / "holdout"
    run_path = sorted((ROOT / "logs").glob("checkpoint3_holdout_run_*.json"))[-1]
    run = json.loads(run_path.read_text(encoding="utf-8"))
    meta = run["holdout_meta"]
    attack_ids = {cid for cid, m in meta.items() if m["attack_class"] == "instruction_injection"}

    items = {}
    for fname in ["t0.json", "t1.json", "t2.json", "t3.json", "t4.json"]:
        for it in json.loads((holdout_dir / fname).read_text(encoding="utf-8")):
            if it["chunk_id"] in attack_ids:
                items[it["chunk_id"]] = {"chunk_id": it["chunk_id"], "schema_type": it["schema_type"],
                                          "chunk": it["chunk"], "population": "attack210"}
    assert len(items) == 210, f"공격 청크 개수 불일치: {len(items)}"

    dev = json.loads((ROOT / "eval" / "dataset" / "pilot" / "pilot1_normal.json").read_text(encoding="utf-8"))
    dev += json.loads((ROOT / "eval" / "dataset" / "pilot" / "pilot2_boilerplate.json").read_text(encoding="utf-8"))
    n_dev = 0
    for it in dev:
        items[it["chunk_id"]] = {"chunk_id": it["chunk_id"], "schema_type": it["schema_type"],
                                  "chunk": it["chunk"], "population": "normal130"}
        n_dev += 1
    for it in json.loads((holdout_dir / "hard_negative.json").read_text(encoding="utf-8")):
        items[it["chunk_id"]] = {"chunk_id": it["chunk_id"], "schema_type": it["schema_type"],
                                  "chunk": it["chunk"], "population": "normal130"}
        n_dev += 1
    assert n_dev == 130, f"정상130 개수 불일치: {n_dev}"

    pa = json.loads((ROOT / "eval" / "dataset" / "dev2_exploration" / "policy_adjacent_normal.json").read_text(encoding="utf-8"))
    for it in pa:
        items[it["chunk_id"]] = {"chunk_id": it["chunk_id"], "schema_type": it["schema_type"],
                                  "chunk": it["chunk"], "population": "policy_adjacent40"}
    assert sum(1 for v in items.values() if v["population"] == "policy_adjacent40") == 40

    assert len(items) == 380, f"전체 개수 불일치: {len(items)}"
    return list(items.values())


def main():
    targets = load_target_380()
    print(f"대상: {len(targets)}건 (공격210 + 정상130 + 정책인접40)")

    schema_types = [it["schema_type"] for it in targets]
    pool = build_query_pool(schema_types, n_per_slot=10, seed=42)
    print(f"질의 풀: schema_type {len(pool)}개")
    leak = leakage_rate(pool)
    print(f"누출률(자체 사전 기준): {leak['rate']:.3f} ({leak['leaked_queries']}/{leak['total_queries']})")
    if leak["rate"] > 0.15:
        print("!!! 누출률이 §11.5 (a) 기준(15%)을 초과한다 — 무효 조건. 그래도 수집은 계속하고 보고에 명시한다.")

    for seed in SEEDS:
        out_path = ROOT / "logs" / f"e1_responses_B_seed{seed}.json"
        results = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
        remaining = [it for it in targets if it["chunk_id"] not in results]
        print(f"\n[seed={seed}] 남은 작업: {len(remaining)}건 (전체 {len(targets)}건 중 {len(results)}건 캐시)")
        start = time.time()
        for i, it in enumerate(remaining, 1):
            context = json.dumps(it["chunk"], ensure_ascii=False)
            queries = sample_queries_for_chunk(pool, it["schema_type"], it["chunk_id"], K, seed)
            responses = [call_chatbot(context, q) for q in queries]
            results[it["chunk_id"]] = {
                "population": it["population"], "schema_type": it["schema_type"],
                "queries": queries, "responses": responses,
            }
            if i % 20 == 0 or i == len(remaining):
                print(f"  [seed={seed}] {i}/{len(remaining)} ({time.time()-start:.0f}s)")
                out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[seed={seed}] 완료: {out_path}")

    print("\n응답 수집 완료. 판정(C' 적용)은 별도 단계에서 한다 — 이 스크립트는 수집만 한다.")


if __name__ == "__main__":
    main()
