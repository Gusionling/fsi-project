"""independent_generated 세트(별도 세션·별도 모델이 생성한, 사람이 직접 작성한 것이
아닌 최종 평가 전용 공격/정상 데이터 — eval/dataset/holdout/human_written.json 자리에
해당하는 파일)를 동결된 B0/B1/B2/B3/M0로 한 번 평가한다. dev 임계값을 그대로 쓰고
재조정하지 않는다.

체크포인트 3(325건)와는 완전히 분리된 로그(logs/human_written_*)를 쓴다 — 이미 확정된
체크포인트 3 결과 파일에 항목을 추가하거나 덮어쓰지 않는다.

**준비만 해두는 스크립트다 — 평가 대상 파일이 채워지기 전까지는 실행하지 않는다.**
eval/dataset/holdout/human_written_template.json의 가이드를 따라(사람이 직접 쓰든,
independent_set.json을 adapt_independent_set.py로 변환하든) 데이터를 만들고
validate_human_written으로 검증을 통과한 뒤에만 실행한다.

실행: EVAL_HUMAN_WRITTEN=1 LLM_MAX_CALLS=20000 python -m eval.decision_experiment.run_human_written_eval
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

from eval.decision_experiment import run_checkpoint3 as cp3  # noqa: E402
from eval.decision_experiment import b0_lexical, b1_llm_judge, b2_kad, b3_whitelist  # noqa: E402
from eval.decision_experiment.common import load_dev_set  # noqa: E402
from eval.decision_experiment.validate_human_written import load_human_written, validate_items, _existing_entities  # noqa: E402

HUMAN_WRITTEN_PATH = ROOT / "eval" / "dataset" / "holdout" / "human_written.json"
HUMAN_WRITTEN_CACHE_DIR = ROOT / "eval" / "decision_experiment" / ".llm_cache_human_written"


def main():
    if os.environ.get("EVAL_HUMAN_WRITTEN", "").lower() not in ("1", "true", "yes"):
        print("EVAL_HUMAN_WRITTEN=1 이 설정되지 않았다. 실수 실행을 막기 위한 안전장치다.")
        sys.exit(1)

    if not HUMAN_WRITTEN_PATH.exists():
        print(f"{HUMAN_WRITTEN_PATH} 가 없다. human_written_template.json을 복사해 먼저 작성하라.")
        sys.exit(1)

    items = load_human_written(HUMAN_WRITTEN_PATH)
    if not items:
        print(f"{HUMAN_WRITTEN_PATH} 에 항목이 없다(비어 있음).")
        sys.exit(1)

    print(f"human_written.json 로드: {len(items)}건 — 검증 중...")
    existing_accounts, existing_urls = _existing_entities()
    errors = validate_items(items, is_template=False, existing_accounts=existing_accounts, existing_urls=existing_urls)
    if errors:
        print(f"검증 실패({len(errors)}건) — 평가 전에 validate_human_written으로 먼저 고쳐라:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("검증 통과.")

    cp3.verify_frozen_hashes()

    llm.CACHE_DIR = HUMAN_WRITTEN_CACHE_DIR
    dev = load_dev_set()
    whitelist = b3_whitelist.build_whitelist(dev)

    print("B0(어휘 기준선) 계산 중...")
    b0_scores = {it["chunk_id"]: b0_lexical.score_chunk(it) for it in items}

    print("B3(정적 엔티티 화이트리스트) 계산 중...")
    b3_flags = {it["chunk_id"]: b3_whitelist.flag_chunk(it, whitelist) for it in items}

    print(f"B1(LLM 단일 판정) 실제 호출: {len(items)}건...")
    b1_results = {it["chunk_id"]: b1_llm_judge.score_chunk(it) for it in items}

    print(f"B2(KAD) 실제 호출: {len(items)}건...")
    b2_results = {it["chunk_id"]: b2_kad.flag_chunk(it) for it in items}

    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    m0_scores = cp3.run_m0(items, logs_dir, probe_log_name="human_written_m0_probes.json")

    out = {
        "human_written_chunk_ids": [it["chunk_id"] for it in items],
        "human_written_meta": {
            it["chunk_id"]: {
                "intent": it.get("intent"),
                "group": it.get("group"),
                "schema_type": it["schema_type"],
                "ground_truth_label": it["ground_truth_label"],
                "attack_class": it.get("attack_class"),
                "scope_marker": it.get("scope_marker"),
            }
            for it in items
        },
        "m0_scores": m0_scores,
        "b0_scores": b0_scores,
        "b1_results": b1_results,
        "b2_results": b2_results,
        "b3_flags": b3_flags,
        "dev_thresholds": cp3.DEV_THRESHOLDS,
        "dev_fpr_rule_met": cp3.DEV_FPR_RULE_MET,
    }
    out_path = logs_dir / f"human_written_eval_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n완료. 원본 결과 저장: {out_path}")


if __name__ == "__main__":
    main()
