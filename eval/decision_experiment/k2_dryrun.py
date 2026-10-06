"""K2(청크 폭파) 대량 호출 전 10청크 드라이런 + 비용 추정 (절대 규칙 9).

실제 디토네이션(챗봇 호출) + C' 판정을 10개 청크에 대해서만 실행해 실측 토큰 사용량을
얻고, 전체 B팔(공격210+정상130+정책인접40=380청크 × K=5 × 시드3) 규모로 환산한
호출 수·추정 비용을 출력하고 멈춘다. 이 스크립트는 그 이상 진행하지 않는다.

실행: LLM_MAX_CALLS=2000 python -m eval.decision_experiment.k2_dryrun
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

llm.CACHE_DIR = ROOT / "eval" / "decision_experiment" / ".llm_cache_k2_dryrun"

from eval.decision_experiment.k2_query_gen import build_query_pool, sample_queries_for_chunk, leakage_rate  # noqa: E402
from eval.decision_experiment.k1_guard import check_response, load_registry_a  # noqa: E402
from eval.decision_experiment.executed_verification import call_chatbot  # noqa: E402

K = 5
SEED = 42


def load_sample_10():
    """공격/정상/정책인접에서 스키마 다양성을 고려해 10건을 뽑는다(결정론적, 내용 참고 없음)."""
    holdout_dir = ROOT / "eval" / "dataset" / "holdout"
    t0 = json.loads((holdout_dir / "t0.json").read_text(encoding="utf-8"))
    hn = json.loads((holdout_dir / "hard_negative.json").read_text(encoding="utf-8"))
    pa = json.loads((ROOT / "eval" / "dataset" / "dev2_exploration" / "policy_adjacent_normal.json").read_text(encoding="utf-8"))
    sample = t0[:5] + hn[:3] + pa[:2]
    return sample


def main():
    sample = load_sample_10()
    print(f"드라이런 샘플: {len(sample)}건")
    schema_types = [it["schema_type"] for it in sample]

    t0 = time.time()
    pool = build_query_pool(schema_types, n_per_slot=10, seed=SEED)
    gen_calls = len(pool)
    print(f"질의 풀 생성: schema_type {gen_calls}개, {time.time()-t0:.1f}s")

    leak = leakage_rate(pool)
    print(f"누출률(자체 어휘 사전 기준): {leak['rate']:.3f} ({leak['leaked_queries']}/{leak['total_queries']}) "
          f"— 기준 27.8%는 이 저장소 밖 자료(ea2 계열)라 재현 못함, 자체 사전으로 참고치만 낸다")
    print(f"  intent별 매치 수: {leak['per_intent_hits']}")

    registry = load_registry_a()

    chat_char_in_total = 0
    chat_char_out_total = 0
    judge_char_in_total = 0
    judge_char_out_total = 0
    n_chat_calls = 0
    n_judge_calls = 0

    results = {}
    start = time.time()
    for it in sample:
        cid = it["chunk_id"]
        context = json.dumps(it["chunk"], ensure_ascii=False)
        queries = sample_queries_for_chunk(pool, it["schema_type"], cid, K, SEED)
        per_query = []
        for q in queries:
            resp = call_chatbot(context, q)
            n_chat_calls += 1
            chat_char_in_total += len(context) + len(q)
            chat_char_out_total += len(resp)
            verdict = check_response(q, resp, registry)
            if verdict.violations["V1"] or verdict.violations["V2"]:
                n_judge_calls += 1  # V1/V2 LLM judge 1회(V4는 로컬 regex, 호출 아님)
                judge_char_in_total += len(q) + len(resp)
                judge_char_out_total += 50  # 대략치(JSON 응답)
            per_query.append({"query": q, "response": resp, "verdict": verdict.to_dict()})
        results[cid] = per_query
        flagged = any(pq["verdict"]["flagged"] for pq in per_query)
        print(f"  {cid}: flagged={flagged}")

    elapsed = time.time() - start
    print(f"\n드라이런 완료: {elapsed:.1f}s, 청크당 평균 {elapsed/len(sample):.1f}s")

    out_path = ROOT / "logs" / "k2_dryrun_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 토큰/비용 추정 (문자 수 -> 대략 토큰 환산, 한국어 혼합 텍스트 기준 1토큰≈2.2자로 근사) ---
    CHARS_PER_TOKEN = 2.2
    chat_calls_total = len(sample) * K  # 실제 호출한 챗봇 콜 수(캐시 미스 기준과 동일, 드라이런엔 캐시 없음 가정)
    avg_chat_in_tok = (chat_char_in_total / max(n_chat_calls, 1)) / CHARS_PER_TOKEN
    avg_chat_out_tok = (chat_char_out_total / max(n_chat_calls, 1)) / CHARS_PER_TOKEN

    print(f"\n[실측 기반] 챗봇 호출 {n_chat_calls}회, 평균 입력≈{avg_chat_in_tok:.0f}토큰, 평균 출력≈{avg_chat_out_tok:.0f}토큰(근사)")
    print(f"[실측 기반] V1/V2 judge 호출 {n_judge_calls}회 (전체 응답 중 judge가 필요했던 비율: {n_judge_calls}/{n_chat_calls})")

    # 전체 B팔 규모
    full_chunks = 210 + 130 + 40  # 공격 + 정상 + 정책인접
    seeds = 3
    full_chat_calls = full_chunks * K * seeds
    # judge 호출 비율은 드라이런 표본 비율을 그대로 외삽(표본이 작아 변동 클 수 있음)
    judge_ratio = n_judge_calls / max(n_chat_calls, 1)
    full_judge_calls = int(full_chat_calls * judge_ratio)
    full_gen_calls = 6  # schema_type 6종, 세션 전체에서 1회

    total_calls = full_chat_calls + full_judge_calls + full_gen_calls
    print(f"\n[전체 B팔 외삽] 청크 {full_chunks}건 × K={K} × 시드{seeds} = 챗봇 호출 {full_chat_calls}회")
    print(f"[전체 B팔 외삽] V1/V2 judge 호출 ≈ {full_judge_calls}회 (드라이런 judge 비율 {judge_ratio:.2f} 외삽)")
    print(f"[전체 B팔 외삽] 총 LLM 호출 ≈ {total_calls}회 (LLM_MAX_CALLS 상한과 비교 필요)")

    # gpt-4o-mini 공개 가격표 기준 개략 추정(실행 시점 가격표 재확인 필요, 여기서는 과거 공개된
    # 대략적 단가를 참고치로만 쓴다 — $0.15/1M input, $0.60/1M output 수준의 과거 공개 가격 기준).
    PRICE_IN_PER_1M = 0.15
    PRICE_OUT_PER_1M = 0.60
    chat_cost = full_chat_calls * (avg_chat_in_tok * PRICE_IN_PER_1M + avg_chat_out_tok * PRICE_OUT_PER_1M) / 1_000_000
    judge_avg_in_tok = (judge_char_in_total / max(n_judge_calls, 1)) / CHARS_PER_TOKEN if n_judge_calls else 150
    judge_cost = full_judge_calls * (judge_avg_in_tok * PRICE_IN_PER_1M + 30 * PRICE_OUT_PER_1M) / 1_000_000
    total_cost = chat_cost + judge_cost
    print(f"\n[비용 추정, 참고치 — 실행 시점 가격표로 재확인 필요] 챗봇 호출 ≈ ${chat_cost:.2f}, judge 호출 ≈ ${judge_cost:.2f}, 합계 ≈ ${total_cost:.2f}")
    print("\n절대 규칙 9: 위 추정치를 출력했으니 여기서 멈춘다. 실행 여부는 사용자가 결정한다.")


if __name__ == "__main__":
    main()
