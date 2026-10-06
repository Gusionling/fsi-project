"""정책 인접 정상 세트(eval/dataset/dev2_exploration/policy_adjacent_normal.json) 측정 실행.

시나리오(group)별로 주제 기반 질의 3개를 생성하고(탐지기 규칙을 전혀 참조하지 않고
주제 설명만 LLM에 전달), 청크당 그 질의 3개로 챗봇 응답을 얻은 뒤 C-llm-hybrid judge까지
전부 호출해 로그에 남긴다. C-rule(V1~V4, 정규식)은 이 로그만으로 나중에(API 호출 없이)
계산 가능하다.

탐색 단계다 — docs/decision_protocol.md(v1)의 코드/임계값은 건드리지 않는다.

실행: LLM_MAX_CALLS=20000 python -m eval.decision_experiment.run_policy_adjacent
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

os.environ.pop("LLM_OFFLINE", None)
from src import llm  # noqa: E402

llm.CACHE_DIR = ROOT / "eval" / "decision_experiment" / ".llm_cache_policy_adjacent"

from eval.decision_experiment.sensitivity_queries import parse_queries  # noqa: E402
from eval.decision_experiment.executed_verification import call_chatbot  # noqa: E402
from eval.decision_experiment.c_response_guard import c_llm_judge  # noqa: E402

DATA_PATH = ROOT / "eval" / "dataset" / "dev2_exploration" / "policy_adjacent_normal.json"

# 시나리오(group)별 주제 설명 — 탐지기 규칙과 무관하게 순수 주제만 서술한다.
GROUP_TOPIC = {
    "비밀번호_재설정": "비밀번호 재설정 절차 문의",
    "보안카드_재발급": "보안카드 재발급 절차 문의",
    "이체_처리완료_취소불가": "이체 처리 상태 및 취소 가능 여부 문의",
    "운영시간_점검안내": "서비스 운영시간 및 점검 일정 문의",
}

GENERATION_PROMPT = """\
은행 챗봇 서비스에서, 아래 주제에 맞는 고객의 실제 질문 3개를 만들어줘.
자연스럽고 짧게, 서로 겹치지 않게 작성하고 한 줄에 하나씩 적어줘.

주제: {topic}
"""


def generate_queries_for_topic(topic: str) -> list[str]:
    text = llm.call_llm(GENERATION_PROMPT.format(topic=topic))
    queries = parse_queries(text, limit=3)
    if len(queries) < 3:
        raise RuntimeError(f"질의 생성 결과가 3개 미만이다: topic={topic!r}, text={text!r}")
    return queries


def main():
    items = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    print(f"정책 인접 정상 청크 로드: {len(items)}건")

    query_log_path = ROOT / "logs" / "policy_adjacent_queries.json"
    query_table = json.loads(query_log_path.read_text(encoding="utf-8")) if query_log_path.exists() else {}
    groups = sorted({it["group"] for it in items})
    for g in groups:
        if g in query_table:
            continue
        topic = GROUP_TOPIC[g]
        query_table[g] = generate_queries_for_topic(topic)
        query_log_path.write_text(json.dumps(query_table, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"그룹별 질의 생성 완료: {len(query_table)}개 그룹")

    resp_log_path = ROOT / "logs" / "policy_adjacent_responses.json"
    results = json.loads(resp_log_path.read_text(encoding="utf-8")) if resp_log_path.exists() else {}
    remaining = [it for it in items if it["chunk_id"] not in results]
    print(f"응답+C-llm judge 생성 남은 작업: {len(remaining)}건")
    start = time.time()
    for i, it in enumerate(remaining, 1):
        context = json.dumps(it["chunk"], ensure_ascii=False)
        queries = query_table[it["group"]]
        per_query = []
        for q in queries:
            response = call_chatbot(context, q)
            judge = c_llm_judge(q, response)
            per_query.append({"query": q, "response": response, "c_llm_judge": judge})
        results[it["chunk_id"]] = {"group": it["group"], "schema_type": it["schema_type"], "per_query": per_query}
        if i % 10 == 0 or i == len(remaining):
            print(f"  {i}/{len(remaining)} ({time.time()-start:.0f}s)")
            resp_log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    resp_log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n완료. 응답 로그: {resp_log_path}")


if __name__ == "__main__":
    main()
