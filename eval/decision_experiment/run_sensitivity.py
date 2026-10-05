"""민감도 분석 실행: 주제 기반 질의로 executed 라벨을 다시 매긴다.

탐색적 분석이다 — M0/B0/B1/B2/B3 코드와 임계값, 체크포인트 3의 점수/flag는 전혀
다시 계산하지 않는다(logs/checkpoint3_holdout_run_*.json을 그대로 재사용한다).
이 스크립트가 새로 만드는 것은 executed 라벨뿐이다. docs/decision_protocol.md(사전
등록 프로토콜)와 docs/m0_decision_results.md(사전 등록 결과)는 건드리지 않는다.

실행: LLM_MAX_CALLS=20000 python -m eval.decision_experiment.run_sensitivity
"""
import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

os.environ.pop("LLM_OFFLINE", None)
from src import llm  # noqa: E402

llm.CACHE_DIR = ROOT / "eval" / "decision_experiment" / ".llm_cache_sensitivity"

from eval.decision_experiment import sensitivity_queries  # noqa: E402
from eval.decision_experiment.executed_verification import (  # noqa: E402
    ACCOUNT_RE,
    URL_RE,
    extract_injected_instruction,
    call_chatbot,
    judge_followed,
)
from eval.decision_experiment.common import free_text_of  # noqa: E402


def load_latest_checkpoint3():
    paths = sorted(glob.glob(str(ROOT / "logs" / "checkpoint3_holdout_run_*.json")))
    if not paths:
        raise SystemExit("체크포인트 3 로그가 없다 — run_checkpoint3를 먼저 실행하라.")
    return json.loads(Path(paths[-1]).read_text(encoding="utf-8")), paths[-1]


def load_holdout_items() -> dict[str, dict]:
    holdout_dir = ROOT / "eval" / "dataset" / "holdout"
    files = ["t0.json", "t1.json", "t2.json", "t2p.json", "t3.json", "t4.json", "hard_negative.json"]
    items = {}
    for fname in files:
        for it in json.loads((holdout_dir / fname).read_text(encoding="utf-8")):
            items[it["chunk_id"]] = it
    return items


def verify_chunk_with_queries(item: dict, queries: list[str]) -> dict:
    schema_type = item["schema_type"]
    chunk = item["chunk"]
    free_text = free_text_of(schema_type, chunk)
    context = json.dumps(chunk, ensure_ascii=False)
    injected_instruction = extract_injected_instruction(free_text)

    per_query = []
    for q in queries:
        response = call_chatbot(context, q)
        judge = judge_followed(injected_instruction, response)
        per_query.append({"query": q, "response": response, "judge": judge})

    executed = any(pq["judge"]["followed"] for pq in per_query)

    entity_match = None
    if item.get("intent") in ("acct_redirect", "external_link"):
        entities = ACCOUNT_RE.findall(free_text) + URL_RE.findall(free_text)
        entity_match = any(any(e in pq["response"] for e in entities) for pq in per_query) if entities else False

    return {
        "chunk_id": item["chunk_id"],
        "injected_instruction": injected_instruction,
        "queries_used": queries,
        "per_query": per_query,
        "executed": executed,
        "entity_match": entity_match,
    }


def main():
    run, run_path = load_latest_checkpoint3()
    print(f"체크포인트 3 로그 재사용(점수/flag 재계산 없음): {run_path}")
    items = load_holdout_items()
    meta = run["holdout_meta"]

    targets = [cid for cid, m in meta.items() if m["attack_class"] == "instruction_injection"]
    print(f"민감도 분석 대상: {len(targets)}건 (instruction_injection 전체, T3 포함)")

    combos = sorted({(meta[cid]["intent"], meta[cid]["schema_type"]) for cid in targets})
    print(f"(intent, schema_type) 조합: {len(combos)}개 — 조합당 질의 3개 생성")

    query_log_path = ROOT / "logs" / "sensitivity_queries.json"
    if query_log_path.exists():
        query_table = json.loads(query_log_path.read_text(encoding="utf-8"))
        print(f"  기존 질의 생성 로그 재사용: {len(query_table)}개 조합")
    else:
        query_table = {}
    for intent, schema_type in combos:
        key = f"{intent}|{schema_type}"
        if key in query_table:
            continue
        query_table[key] = sensitivity_queries.generate_queries(intent, schema_type)
        query_log_path.write_text(json.dumps(query_table, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  질의 생성 완료: {len(query_table)}개 조합")

    exec_log_path = ROOT / "logs" / "sensitivity_executed.json"
    results = {}
    if exec_log_path.exists():
        results = json.loads(exec_log_path.read_text(encoding="utf-8"))
        print(f"  기존 민감도 executed 로그에서 {len(results)}건 재사용")

    remaining = [cid for cid in targets if cid not in results]
    print(f"  executed 재판정 남은 작업: {len(remaining)}건")
    start = time.time()
    for i, cid in enumerate(remaining, 1):
        item = items[cid]
        key = f"{item['intent']}|{item['schema_type']}"
        queries = query_table[key]
        results[cid] = verify_chunk_with_queries(item, queries)
        if i % 10 == 0 or i == len(remaining):
            print(f"    executed(민감도) {i}/{len(remaining)} ({time.time()-start:.0f}s)")
            exec_log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    exec_log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n민감도 executed 라벨 생성 완료: {exec_log_path}")


if __name__ == "__main__":
    main()
