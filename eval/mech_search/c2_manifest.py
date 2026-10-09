"""C2 Phase 2 추출 대상 목록(manifest) 빌더. API 호출 없음, 기존 로그만 읽는다.

docs/decision_protocol_v3.md §11/§12에서 확정한 대상:
  - 정상 170청크(130+40) × 응답 3개 = 510건
  - 공격 info_exfil arm A 42청크 × 3 = 126건
  - 공격 info_exfil arm C 42청크 × 3 = 126건
  - 주입 간이 실험 30건
  총 792건(1차·2차 각각).
"""
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

LOGS = ROOT / "logs"
INJECTION_PATH = Path(__file__).resolve().parent / "c2_injection_lite.json"


def _load(name: str) -> dict[str, Any]:
    return json.loads((LOGS / name).read_text(encoding="utf-8"))


def build_manifest() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    normal = _load("normal_baseline_responses.json")
    for chunk_id, v in normal.items():
        for i, (query, response) in enumerate(zip(v["queries"], v["responses"])):
            items.append({
                "id": f"normal_baseline:{chunk_id}:{i}",
                "category": "normal",
                "layer": "일반",
                "chunk_id": chunk_id,
                "query_idx": i,
                "response": response,
                "ground_truth_violated": False,
                "executed_response": None,
            })

    policy = _load("policy_adjacent_responses.json")
    for chunk_id, v in policy.items():
        for i, q in enumerate(v["per_query"]):
            items.append({
                "id": f"policy_adjacent:{chunk_id}:{i}",
                "category": "normal",
                "layer": "정책인접",
                "chunk_id": chunk_id,
                "query_idx": i,
                "response": q["response"],
                "ground_truth_violated": False,
                "executed_response": None,
            })

    checkpoint3 = _load("checkpoint3_executed.json")
    for chunk_id, v in checkpoint3.items():
        if "info_exfil" not in chunk_id:
            continue
        for i, q in enumerate(v["per_query"]):
            items.append({
                "id": f"armA:{chunk_id}:{i}",
                "category": "attack_info_exfil",
                "arm": "A",
                "chunk_id": chunk_id,
                "query_idx": i,
                "response": q["response"],
                "ground_truth_violated": None,  # D1/§4 라벨은 B1/C2 판정으로 별도 계산한다
                "executed_response": bool(q["judge"]["followed"]),
                "executed_chunk": bool(v["executed"]),
            })

    sensitivity = _load("sensitivity_executed.json")
    for chunk_id, v in sensitivity.items():
        if "info_exfil" not in chunk_id:
            continue
        for i, q in enumerate(v["per_query"]):
            items.append({
                "id": f"armC:{chunk_id}:{i}",
                "category": "attack_info_exfil",
                "arm": "C",
                "chunk_id": chunk_id,
                "query_idx": i,
                "response": q["response"],
                "ground_truth_violated": None,
                "executed_response": bool(q["judge"]["followed"]),
                "executed_chunk": bool(v["executed"]),
            })

    injection = json.loads(INJECTION_PATH.read_text(encoding="utf-8"))
    for it in injection["items"]:
        items.append({
            "id": it["id"],
            "category": "injection_lite",
            "injection_category": it["category"],
            "response": it["response"],
            "ground_truth_violated": it["ground_truth_violated"],
            "executed_response": None,
        })

    return items


if __name__ == "__main__":
    manifest = build_manifest()
    by_category: dict[str, int] = {}
    for it in manifest:
        by_category[it["category"]] = by_category.get(it["category"], 0) + 1
    print("총 건수:", len(manifest))
    print(by_category)
