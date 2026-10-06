"""정책 인접 정상 세트 측정 보고서 — logs/policy_adjacent_responses.json(이미 생성된
응답 + C-llm judge 결과)만으로 C-rule/C-llm-hybrid의 청크·응답 단위 FPR을 계산해
docs/policy_adjacent_results.md를 만든다. 새 API 호출 없음(로컬 집계).

docs/decision_protocol.md(v1)·동결 코드는 건드리지 않는다. 판단 문장은 쓰지 않는다.

실행: python -m eval.decision_experiment.build_policy_adjacent_report
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from eval.decision_experiment.c_response_guard import c_rule_violations, c_llm_hybrid_violations  # noqa: E402
from eval.decision_experiment.common import wilson_ci, load_dev_set  # noqa: E402
from eval.decision_experiment.b3_whitelist import build_whitelist  # noqa: E402

RULES = ["V1", "V2", "V3", "V4"]


def main():
    resp_path = ROOT / "logs" / "policy_adjacent_responses.json"
    results = json.loads(resp_path.read_text(encoding="utf-8"))

    dev = load_dev_set()
    whitelist = build_whitelist(dev)  # 등록부 (a), §5.2 지침대로

    # 청크별로 각 규칙 체계(C-rule / C-llm-hybrid)의 per-query violation을 계산해 둔다.
    chunk_violations_rule = {}
    chunk_violations_llm = {}
    response_flat = []  # (chunk_id, query, response, c_rule_v, c_llm_v)

    for cid, entry in results.items():
        rule_vs, llm_vs = [], []
        for pq in entry["per_query"]:
            rv = c_rule_violations(pq["response"], whitelist)
            lv = c_llm_hybrid_violations(pq["query"], pq["response"], whitelist, judge_result=pq["c_llm_judge"])
            rule_vs.append(rv)
            llm_vs.append(lv)
            response_flat.append((cid, pq["query"], pq["response"], rv, lv))
        chunk_violations_rule[cid] = rule_vs
        chunk_violations_llm[cid] = llm_vs

    n_chunks = len(results)
    n_responses = len(response_flat)

    def chunk_fpr(violations_by_chunk: dict, rule: str | None) -> tuple[float, float, float, int]:
        """rule=None이면 '4가지 중 하나라도'."""
        hit = 0
        for cid, vs in violations_by_chunk.items():
            if rule is None:
                flagged = any(any(v.values()) for v in vs)
            else:
                flagged = any(v[rule] for v in vs)
            hit += int(flagged)
        return (*wilson_ci(hit, n_chunks), hit)

    def response_fpr(violations_by_chunk: dict, rule: str | None) -> tuple[float, float, float, int]:
        hit = 0
        for vs in violations_by_chunk.values():
            for v in vs:
                flagged = any(v.values()) if rule is None else v[rule]
                hit += int(flagged)
        return (*wilson_ci(hit, n_responses), hit)

    def fmt(t):
        p, lo, hi, c = t
        return f"{p:.3f} [{lo:.3f}, {hi:.3f}] ({c})"

    lines = []
    lines.append("# 정책 인접 정상 세트 측정 (탐색) — C-rule / C-llm-hybrid 오탐률")
    lines.append("")
    lines.append(
        "> `eval/dataset/dev2_exploration/policy_adjacent_normal.json`(40건, dev2 탐색용 "
        "신규 정상 데이터 — 비밀번호 재설정/보안카드 재발급/이체 처리완료·취소불가/운영시간·"
        "점검안내 4개 시나리오×10건)에 시나리오 단위로 생성한 질의 3개를 돌려 얻은 응답에 "
        "C-rule(V1~V4, 정규식, 등록부는 dev 정상 청크 기준)과 C-llm-hybrid(V1~V3는 LLM "
        "판정, V4는 C-rule과 동일 정규식)를 적용했다. 생성 지침은 "
        "`docs/decision_protocol_v2.md` §5.2에 기록했다. 새 API 호출 없이 "
        "`logs/policy_adjacent_responses.json`만 썼다. 판단 문장은 쓰지 않는다."
    )
    lines.append("")
    lines.append(f"- 청크 수: {n_chunks}, 응답 수: {n_responses} (청크당 질의 3개)")
    lines.append("")

    for label, by_chunk in [("C-rule", chunk_violations_rule), ("C-llm-hybrid", chunk_violations_llm)]:
        lines.append(f"## {label}")
        lines.append("")
        lines.append("| 규칙 | 청크 단위 FPR | 응답 단위 FPR |")
        lines.append("|---|---|---|")
        for rule in RULES:
            lines.append(f"| {rule} | {fmt(chunk_fpr(by_chunk, rule))} | {fmt(response_fpr(by_chunk, rule))} |")
        lines.append(f"| 4가지 중 하나라도 | {fmt(chunk_fpr(by_chunk, None))} | {fmt(response_fpr(by_chunk, None))} |")
        lines.append("")

    # 위반 응답 발췌 목록
    lines.append("## 위반으로 판정된 응답 (원문 발췌 + 걸린 규칙)")
    lines.append("")
    any_violation = False
    for cid, query, response, rv, lv in response_flat:
        rv_hit = [r for r in RULES if rv[r]]
        lv_hit = [r for r in RULES if lv[r]]
        if not rv_hit and not lv_hit:
            continue
        any_violation = True
        lines.append(f"**{cid}** — 질의: {query!r}")
        lines.append(f"- 응답: {response!r}")
        lines.append(f"- C-rule 걸림: {rv_hit if rv_hit else '없음'}")
        lines.append(f"- C-llm-hybrid 걸림: {lv_hit if lv_hit else '없음'}")
        lines.append("")
    if not any_violation:
        lines.append("(해당 없음 — 위반으로 판정된 응답이 없다)")
        lines.append("")

    out_path = ROOT / "docs" / "policy_adjacent_results.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"작성 완료: {out_path}")


if __name__ == "__main__":
    main()
