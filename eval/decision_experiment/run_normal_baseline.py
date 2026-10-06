"""정상 응답 기준선 측정 실행 — dev(파일럿 정상 90) + dev2(구 holdout) hard_negative 40건,
총 130건에 schema_type 기반 질의 3개로 챗봇을 돌려 응답만 모은다(judge 없음 — 응답에
build_followup_report의 V1~V4 규칙을 그대로 적용하는 것은 별도 리포트 스크립트가 한다).

탐색적 분석이다. M0/B0/B1/B2/B3 코드나 docs/decision_protocol.md는 건드리지 않는다.

실행: LLM_MAX_CALLS=20000 python -m eval.decision_experiment.run_normal_baseline
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

llm.CACHE_DIR = ROOT / "eval" / "decision_experiment" / ".llm_cache_normal_baseline"

from eval.decision_experiment import normal_baseline_queries  # noqa: E402
from eval.decision_experiment.executed_verification import call_chatbot  # noqa: E402
from eval.decision_experiment.common import load_dev_set  # noqa: E402


def load_normal_items() -> list[dict]:
    dev = load_dev_set()
    dev_normal = [d for d in dev if d["ground_truth_label"] == "normal"]
    for d in dev_normal:
        d["_source"] = "dev"

    hard_negative = json.loads(
        (ROOT / "eval" / "dataset" / "holdout" / "hard_negative.json").read_text(encoding="utf-8")
    )
    for h in hard_negative:
        h["_source"] = "dev2_hard_negative"

    items = dev_normal + hard_negative
    ids = [it["chunk_id"] for it in items]
    assert len(ids) == len(set(ids)), "dev/dev2 chunk_id 충돌"
    return items


def main():
    items = load_normal_items()
    print(f"정상 청크 로드: {len(items)}건 (dev {sum(1 for i in items if i['_source']=='dev')} + "
          f"dev2_hard_negative {sum(1 for i in items if i['_source']=='dev2_hard_negative')})")

    query_log_path = ROOT / "logs" / "normal_baseline_queries.json"
    query_table = json.loads(query_log_path.read_text(encoding="utf-8")) if query_log_path.exists() else {}
    schema_types = sorted({it["schema_type"] for it in items})
    for st in schema_types:
        if st in query_table:
            continue
        query_table[st] = normal_baseline_queries.generate_queries(st)
        query_log_path.write_text(json.dumps(query_table, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"schema_type별 질의 생성 완료: {len(query_table)}개")

    resp_log_path = ROOT / "logs" / "normal_baseline_responses.json"
    results = json.loads(resp_log_path.read_text(encoding="utf-8")) if resp_log_path.exists() else {}
    remaining = [it for it in items if it["chunk_id"] not in results]
    print(f"응답 생성 남은 작업: {len(remaining)}건")
    start = time.time()
    for i, it in enumerate(remaining, 1):
        context = json.dumps(it["chunk"], ensure_ascii=False)
        queries = query_table[it["schema_type"]]
        responses = [call_chatbot(context, q) for q in queries]
        results[it["chunk_id"]] = {
            "source": it["_source"],
            "schema_type": it["schema_type"],
            "queries": queries,
            "responses": responses,
        }
        if i % 20 == 0 or i == len(remaining):
            print(f"  {i}/{len(remaining)} ({time.time()-start:.0f}s)")
            resp_log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    resp_log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n완료. 응답 로그: {resp_log_path}")


if __name__ == "__main__":
    main()
