"""민감도 분석 보고서 작성: logs/sensitivity_executed.json(주제 기반 질의로 재판정한
executed 라벨)과 체크포인트 3의 탐지기 점수/flag(재계산 없이 그대로 재사용)를 결합해
docs/m0_decision_sensitivity.md를 만든다.

탐색적 분석이다 — docs/decision_protocol.md와 docs/m0_decision_results.md(사전 등록
결과)는 건드리지 않고, 이 문서에 사전 등록 결과와 나란히만 보고한다. 해석 문장
("어느 쪽이 낫다")은 쓰지 않는다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from eval.decision_experiment import build_decision_report as base  # noqa: E402

ALL_METHODS = base.ALL_METHODS


def main():
    run, run_path = base.load_latest_run()
    items = base.load_holdout_items()
    flagged, score, b2_flags, b3_flags = base.build_score_tables(run)
    meta = run["holdout_meta"]

    prereg_executed = run["executed_results"]

    sens_path = ROOT / "logs" / "sensitivity_executed.json"
    if not sens_path.exists():
        raise SystemExit(f"{sens_path} 가 없다 — run_sensitivity를 먼저 실행하라.")
    sens_executed = json.loads(sens_path.read_text(encoding="utf-8"))

    query_table_path = ROOT / "logs" / "sensitivity_queries.json"
    query_table = json.loads(query_table_path.read_text(encoding="utf-8")) if query_table_path.exists() else {}

    def is_executed(cid, source):
        r = source.get(cid)
        return bool(r and r["executed"])

    def tier_ids(tier, attack_class=None, group_prefix=None):
        out = []
        for cid, m in meta.items():
            if m["tier"] != tier:
                continue
            if attack_class is not None and m["attack_class"] != attack_class:
                continue
            if group_prefix is not None and not (m["group"] or "").startswith(group_prefix):
                continue
            out.append(cid)
        return out

    tier_defs = {
        "T0": tier_ids("T0", "instruction_injection"),
        "T1": tier_ids("T1", "instruction_injection"),
        "T2": tier_ids("T2", "instruction_injection"),
        "T3": tier_ids("T3", "instruction_injection"),
        "T4": tier_ids("T4", "instruction_injection"),
        "T4_b0_evasion": tier_ids("T4", "instruction_injection", "b0_evasion"),
        "T4_b1_evasion": tier_ids("T4", "instruction_injection", "b1_evasion"),
        "T4_b2_evasion": tier_ids("T4", "instruction_injection", "b2_evasion"),
    }

    lines = []
    lines.append("# 민감도 분석 — 주제 기반 질의로 executed 재판정 (탐색적, 사전 등록 외)")
    lines.append("")
    lines.append(
        "> `docs/sensitivity_query_generation.md`의 절차로, 6절의 고정 질의(T3는 자신의 "
        "`trigger_queries`) 대신 **(intent, schema_type) 조합별로 주제에서 파생한 질의 3개**를 "
        "새로 생성해 모든 티어에 동일하게 적용하고 executed 라벨을 다시 매겼다. 탐지기 "
        "(M0/B0/B1/B2/B3)의 점수·flag·임계값은 체크포인트 3 그대로 재사용했다(재계산 없음). "
        "사전 등록 결과(`docs/m0_decision_results.md`)는 수정하지 않았고, 아래는 둘을 나란히 "
        "비교한 수치일 뿐 \"어느 쪽이 맞다/낫다\"는 해석 문장은 쓰지 않는다."
    )
    lines.append("")
    lines.append(f"- 체크포인트 3 로그: `{Path(run_path).relative_to(ROOT)}`")
    lines.append(f"- 민감도 executed 로그: `logs/sensitivity_executed.json`")
    lines.append(f"- 질의 생성 조합 수: {len(query_table)}개 (intent×schema_type)")
    lines.append("")

    # ============ A. executed 비율 비교 ============
    lines.append("## A. executed 비율 비교 (사전 등록 vs 민감도)")
    lines.append("")
    lines.append("| 티어/그룹 | n(instruction_injection) | 사전 등록 executed 비율 | 민감도 executed 비율 |")
    lines.append("|---|---|---|---|")
    for tier_name in ["T0", "T1", "T2", "T3", "T4", "T4_b0_evasion", "T4_b1_evasion", "T4_b2_evasion"]:
        ids = tier_defs[tier_name]
        n = len(ids)
        if n == 0:
            lines.append(f"| {tier_name} | 0 | n/a | n/a |")
            continue
        p_ratio = sum(1 for cid in ids if is_executed(cid, prereg_executed)) / n
        s_ratio = sum(1 for cid in ids if is_executed(cid, sens_executed)) / n
        lines.append(f"| {tier_name} | {n} | {p_ratio:.3f} | {s_ratio:.3f} |")
    lines.append("")

    # ============ B. 티어별 recall(executed 중) 비교 ============
    lines.append("## B. 티어별 recall(executed 중) 비교 (사전 등록 vs 민감도)")
    lines.append("")
    header = "| 티어/그룹 | 기준 | " + " | ".join(f"{m} recall" for m in ALL_METHODS) + " |"
    lines.append(header)
    lines.append("|---" * (2 + len(ALL_METHODS)) + "|")
    for tier_name in ["T0", "T1", "T2", "T3", "T4", "T4_b0_evasion", "T4_b1_evasion", "T4_b2_evasion"]:
        ids = tier_defs[tier_name]
        for label, source in [("사전 등록", prereg_executed), ("민감도", sens_executed)]:
            exec_ids = [cid for cid in ids if is_executed(cid, source)]
            cells = []
            for m in ALL_METHODS:
                r = base.recall_row(flagged, m, exec_ids)
                cells.append(base.fmt_ci(r["p"], r["lo"], r["hi"]))
            lines.append(f"| {tier_name} | {label}(n={len(exec_ids)}) | " + " | ".join(cells) + " |")
    lines.append("")

    # ============ C. T1+T2+T3 합산 비교 ============
    lines.append("## C. T1+T2+T3 합산 recall(executed 중) 비교, M0 vs 최고 베이스라인")
    lines.append("")
    lines.append("| 기준 | n(executed) | M0 recall | 최고 베이스라인 | 베이스라인 recall | 격차(M0-베이스라인) | 부트스트랩 95% CI | 0 포함? |")
    lines.append("|---|---|---|---|---|---|---|---|")
    baselines = ["B0", "B1", "B2", "B3"]
    for label, source in [("사전 등록", prereg_executed), ("민감도", sens_executed)]:
        ids = [cid for cid in (tier_defs["T1"] + tier_defs["T2"] + tier_defs["T3"]) if is_executed(cid, source)]
        if not ids:
            lines.append(f"| {label} | 0 | - | - | - | - | - | - |")
            continue
        best_m, best_p = None, -1.0
        for m in baselines:
            r = base.recall_row(flagged, m, ids)
            if r["p"] == r["p"] and r["p"] > best_p:
                best_p, best_m = r["p"], m
        r_m0 = base.recall_row(flagged, "M0", ids)
        r_best = base.recall_row(flagged, best_m, ids)
        point, lo, hi = base.paired_bootstrap_diff(flagged, "M0", best_m, ids)
        contains_zero = "포함" if lo <= 0 <= hi else "미포함"
        lines.append(
            f"| {label} | {len(ids)} | {base.fmt_ci(r_m0['p'], r_m0['lo'], r_m0['hi'])} | {best_m} | "
            f"{base.fmt_ci(r_best['p'], r_best['lo'], r_best['hi'])} | {point:+.3f} | "
            f"[{lo:+.3f}, {hi:+.3f}] | {contains_zero} |"
        )
    lines.append("")

    # ============ D. T4 타깃/전이 표 비교 ============
    lines.append("## D. T4 타깃(targeted)/전이(transfer) recall(executed 중) 비교 (4절 정의 그대로)")
    lines.append("")
    b0_evasion_ii = tier_defs["T4_b0_evasion"]
    b1_evasion_ii = tier_defs["T4_b1_evasion"]
    b2_evasion_ii = tier_defs["T4_b2_evasion"]

    def t4_defs_for(source):
        def e(ids):
            return [cid for cid in ids if is_executed(cid, source)]
        return {
            "B1": {"targeted": e(b1_evasion_ii), "transfer": e(b0_evasion_ii + b2_evasion_ii)},
            "B2": {"targeted": e(b2_evasion_ii), "transfer": e(b0_evasion_ii + b1_evasion_ii)},
            "B0": {"targeted": e(b0_evasion_ii), "transfer": e(b1_evasion_ii + b2_evasion_ii)},
            "M0": {"targeted": e(tier_defs["T3"]), "transfer": e(tier_defs["T4"])},
            "B3": {"targeted": None, "transfer": e(tier_defs["T4"])},
        }

    lines.append("| 방법 | 기준 | 맞춤 n | 맞춤 recall | 전이 n | 전이 recall |")
    lines.append("|---|---|---|---|---|---|")
    for m in ALL_METHODS:
        for label, source in [("사전 등록", prereg_executed), ("민감도", sens_executed)]:
            d = t4_defs_for(source)[m]
            if d["targeted"] is None:
                t_n, t_cell = "-", "-(설계되지 않음)"
            else:
                r = base.recall_row(flagged, m, d["targeted"])
                t_n, t_cell = len(d["targeted"]), base.fmt_ci(r["p"], r["lo"], r["hi"])
            r2 = base.recall_row(flagged, m, d["transfer"])
            lines.append(f"| {m} | {label} | {t_n} | {t_cell} | {len(d['transfer'])} | {base.fmt_ci(r2['p'], r2['lo'], r2['hi'])} |")
    lines.append(
        "\n> M0의 \"맞춤\" 행은 두 기준 모두 T3 recall이다(M0를 직접 겨냥한 티어는 T3뿐 — "
        "decision_protocol.md 4.5절)."
    )
    lines.append("")

    out_path = ROOT / "docs" / "m0_decision_sensitivity.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"작성 완료: {out_path}")


if __name__ == "__main__":
    main()
