"""시연용 CLI — K1(C')·C2 응답 가드레일 데모.

QueryIPI 핵심 메커니즘(질의 불변성 검사, src/pipeline.py 등)은 아직 스텁이라 이
데모는 대신 실제로 동결·실측된 두 응답 가드레일을 보여준다.
  - K1(=C'): V1/V2 LLM judge + V4 정규식·등록부 대조 (eval/decision_experiment/k1_guard.py)
  - C2: 자격증명 싱크 구조화 추출 + 순수 함수 판정 (eval/mech_search/c2_sink.py, c2_extract.py)

판정 로직 자체는 동결된 원본을 그대로 가져다 쓴다 — 여기서 수정하지 않는다.
C2의 LLM 추출 호출(call_extractor)은 C2 실험에서부터 이미 src/llm.py의 call_llm을
거치지 않고 자체 OpenAI 클라이언트를 쓴다(§8에서 정한 1차/2차 모델 역할 분리 때문).
이 데모는 그 동결된 경로를 그대로 재사용하며 바꾸지 않는다.

--offline: demo/scenarios.json에 미리 기록된 K1 judge 결과·C2 추출 결과를 재생한다.
           실제 LLM 호출이 전혀 없다(V4 정규식·C2 decide_violation 판정 로직은 그대로 실행된다).
생략(기본): 실제로 LLM을 호출한다 — 매 호출 전에 비용 발생을 알리고 확인을 받는다.
           직접 입력(자유 텍스트) 시나리오는 사전 기록이 없어 항상 이 경로를 쓴다.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.decision_experiment.k1_guard import check_response, load_registry_a, GuardVerdict  # noqa: E402
from eval.mech_search.c2_sink import decide_response, load_official_sinks  # noqa: E402
from eval.mech_search.c2_extract import call_extractor, PRIMARY_MODEL  # noqa: E402

SCENARIOS_PATH = Path(__file__).resolve().parent / "scenarios.json"


def load_scenarios() -> dict[str, dict[str, Any]]:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def run_k1(query: str, response: str, offline: bool, judge_result: dict[str, Any] | None = None) -> GuardVerdict:
    """K1 판정을 실행한다. offline=True면 judge_result(사전 기록)를 그대로 쓰고 LLM을 호출하지 않는다.
    V4(정규식+등록부 대조)는 offline 여부와 무관하게 항상 실제로 실행된다."""
    registry = load_registry_a()
    if offline:
        if judge_result is None:
            raise ValueError(
                "오프라인 모드인데 사전 기록된 k1_judge_result가 없다 — "
                "자유 입력은 오프라인 재생을 지원하지 않는다."
            )
        return check_response(query, response, registry, judge_result=judge_result)
    return check_response(query, response, registry)


def run_c2(
    response: str, offline: bool, extraction: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """C2 판정을 실행한다. offline=True면 extraction(사전 기록)을 그대로 쓰고 LLM을 호출하지 않는다.
    decide_response(순수 함수, 등록부 대조)는 offline 여부와 무관하게 항상 실제로 실행된다."""
    sinks = load_official_sinks()
    if offline:
        if extraction is None:
            raise ValueError(
                "오프라인 모드인데 사전 기록된 c2_extraction이 없다 — "
                "자유 입력은 오프라인 재생을 지원하지 않는다."
            )
    else:
        result = call_extractor(response, model=PRIMARY_MODEL)
        extraction = result["extraction"]
    decision = decide_response(extraction, sinks)
    return extraction, decision


def limitation_notes(k1_verdict: GuardVerdict, c2_decision: dict[str, Any]) -> list[str]:
    """이 시나리오에서 실제로 걸린 규칙에 해당하는 알려진 한계만 뽑아서 보여준다."""
    notes = []
    if k1_verdict.violations.get("V1"):
        notes.append(
            "K1-V1 judge 프롬프트는 2026-10-06에 탐색적(사후 튜닝) 수정을 1회 거쳤다 — "
            "수정 전 버전은 거래 필드 숫자 노출을 인증정보 요구로 오탐했다(정상 130건 중 17건, 13.1%)."
        )
    for item in c2_decision.get("items", []):
        if item.get("sink_type") == "공식_앱_화면" and not item.get("violated"):
            notes.append(
                "C2의 공식_앱_화면 분기는 등록부 대조 없이 sink_value 존재만으로 통과시키는 신뢰 지점이다 — "
                "추출기가 sink_type을 올바르게 분류했는지에 그대로 의존한다(docs/decision_protocol_v3.md §7)."
            )
    return notes


def run_scenario(scenario: dict[str, Any], offline: bool = True) -> dict[str, Any]:
    query = scenario["query"]
    response = scenario["response"]
    k1_verdict = run_k1(query, response, offline, scenario.get("k1_judge_result"))
    extraction, c2_decision = run_c2(response, offline, scenario.get("c2_extraction"))
    return {
        "k1_verdict": k1_verdict,
        "c2_extraction": extraction,
        "c2_decision": c2_decision,
        "blocked": k1_verdict.flagged or c2_decision["violated"],
    }


def format_report(scenario: dict[str, Any], result: dict[str, Any]) -> str:
    k1 = result["k1_verdict"]
    c2 = result["c2_decision"]
    lines = ["=" * 60]
    if scenario.get("label"):
        lines.append(f"[시나리오] {scenario['label']}")
    lines.append(f"[입력] 질의: {scenario['query']}")
    lines.append(f"       응답: {scenario['response']}")
    lines.append("-" * 60)

    lines.append("[1단계] K1-V1/V2 — LLM judge (인증정보 요구 / 시스템프롬프트 노출)")
    lines.append(f"  V1(인증정보 요구)       : {k1.violations['V1']}")
    lines.append(f"  V2(시스템프롬프트 노출) : {k1.violations['V2']}")
    reason = k1.evidence.get("V1") or k1.evidence.get("V2")
    if reason:
        lines.append(f"  판정 근거: {reason}")

    lines.append("")
    lines.append("[2단계] K1-V4 — 정규식 + 등록부(a) 대조")
    v4_hit = k1.evidence.get("V4")
    v4_line = f"  V4(미등록 계좌/URL/전화): {k1.violations['V4']}"
    if v4_hit:
        v4_line += f" — 매칭값: {v4_hit}"
    lines.append(v4_line)

    lines.append("")
    lines.append("[3단계] C2 — 구조화 추출 (LLM은 판정자가 아니라 추출기)")
    items = c2.get("items", [])
    if not items:
        lines.append("  추출된 항목 없음(credential 요구 패턴을 찾지 못함)")
    else:
        for i, item in enumerate(items, 1):
            lines.append(
                f"  item {i}: credential_type={item['credential_type']} sink_type={item['sink_type']} "
                f"sink_value={item.get('sink_value')} negated={item['negated']}"
            )

    lines.append("")
    lines.append("[4단계] C2 — decide_violation (순수 함수, 등록부 대조·전제 정책)")
    if not items:
        lines.append("  판정 대상 없음 → 위반 아님")
    else:
        for i, item in enumerate(items, 1):
            lines.append(f"  item {i}: 위반={item['violated']}")

    lines.append("-" * 60)
    fired = []
    if k1.violations["V1"]:
        fired.append("K1-V1")
    if k1.violations["V2"]:
        fired.append("K1-V2")
    if k1.violations["V4"]:
        fired.append("K1-V4")
    if c2["violated"]:
        fired.append("C2")
    verdict_line = f"[최종 판정] {'BLOCK' if result['blocked'] else 'PASS'}"
    if fired:
        verdict_line += f" (걸린 규칙: {', '.join(fired)})"
    lines.append(verdict_line)

    notes = limitation_notes(k1, c2)
    if scenario.get("note"):
        notes.append(scenario["note"])
    for note in notes:
        lines.append(f"  ⚠ 한계/참고: {note}")
    lines.append("=" * 60)
    return "\n".join(lines)


def _default_confirm(message: str) -> bool:
    answer = input(f"{message} 계속할까요? (y/n): ").strip().lower()
    return answer == "y"


def main(argv: list[str] | None = None, confirm: Callable[[str], bool] = _default_confirm) -> None:
    parser = argparse.ArgumentParser(description="QueryIPI K1/C2 응답 가드레일 데모")
    parser.add_argument("--offline", action="store_true", help="사전 기록된 판정 결과를 재생한다(LLM 호출 없음)")
    args = parser.parse_args(argv)

    scenarios = load_scenarios()
    ids = list(scenarios.keys())

    while True:
        print("\n시나리오를 선택하세요:")
        for i, sid in enumerate(ids, 1):
            print(f"  {i}. {scenarios[sid]['label']}")
        print("  c. 직접 입력(자유 텍스트, 실제 LLM 호출)")
        print("  q. 종료")
        choice = input("> ").strip().lower()

        if choice == "q":
            break

        if choice == "c":
            if args.offline:
                print("오프라인 모드에서는 직접 입력을 지원하지 않는다 — 사전 기록이 없어 재생할 수 없다.")
                continue
            if not confirm("직접 입력한 응답에 대해 실제 LLM API를 호출한다(K1 judge + C2 추출, 비용 발생)."):
                print("취소했다.")
                continue
            query = input("질의(query): ").strip()
            response = input("응답(response): ").strip()
            scenario = {"label": "직접 입력", "query": query, "response": response, "note": None}
            result = run_scenario(scenario, offline=False)
            print(format_report(scenario, result))
            continue

        try:
            idx = int(choice) - 1
            if idx < 0:
                raise ValueError
            sid = ids[idx]
        except (ValueError, IndexError):
            print("잘못된 선택이다.")
            continue

        scenario = scenarios[sid]
        if not args.offline:
            if not confirm(f"'{scenario['label']}' 시나리오에 대해 실제 LLM API를 호출한다(비용 발생)."):
                print("취소했다.")
                continue
        result = run_scenario(scenario, offline=args.offline)
        print(format_report(scenario, result))


if __name__ == "__main__":
    main()
