"""QueryIPI 중간발표 시연 — Streamlit 웹 UI.

CLI 데모(demo/cli_demo.py)와 똑같은 K1/C2 판정 로직을 재사용한다. 판정 로직은
여기서 새로 만들지 않고 cli_demo의 run_scenario/limitation_notes를 그대로 가져다
쓴다.

화면 구성 (st.session_state["page"]로 전환):
  landing  — 데모 설명 + '기존 데이터셋 이용하기' / '직접 입력하기' 진입
  dataset  — 사전 구성된 시나리오 목록·구성 방식을 보여주고 하나를 골라 실행
  direct   — 사용자가 직접 입력한 (질의, 응답)을 실제 LLM 호출로 검사(비용 발생, 확인 필요)
  result   — 4단계 파이프라인 시각화 + 최종 판정 + 한계 노출

주의: K1/C2는 '공격 질의' 자체가 아니라 '챗봇이 이미 생성한 응답'을 검사한다.
직접 입력 화면에서는 이 전제를 명확히 안내한다(혼동 방지).

실행: streamlit run demo/streamlit_app.py
"""
import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.cli_demo import load_scenarios, run_scenario, limitation_notes  # noqa: E402

st.set_page_config(page_title="QueryIPI 데모", layout="wide")


def _goto(page: str) -> None:
    st.session_state["page"] = page


def build_dataset_table(scenarios: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """데이터셋 구성 화면에 보여줄 테이블 행을 만든다(순수 함수, UI 호출 없음 — 테스트 가능)."""
    rows = []
    for sid, s in scenarios.items():
        response = s["response"]
        rows.append(
            {
                "id": sid,
                "라벨": s["label"],
                "질의": s["query"],
                "응답(일부)": response[:40] + "…" if len(response) > 40 else response,
            }
        )
    return rows


def render_landing() -> None:
    st.title("QueryIPI 데모 — 공격 응답, 어디서 왜 막히는가")
    st.markdown(
        "RAG 챗봇의 응답을 두 가지 응답 가드레일로 검사합니다.\n\n"
        "- **K1**: LLM judge(V1 인증정보 요구 · V2 시스템프롬프트 노출) + 정규식/등록부 대조(V4)\n"
        "- **C2**: LLM이 '비밀정보가 어디로(sink) 향하는가'만 구조화 추출하고, "
        "판정은 방어자가 소유한 공식 싱크 등록부 대조가 결정\n\n"
        "단순히 통과/차단만 보여주지 않고, **4단계 중 어느 지점에서 왜** 걸렸는지를 보여줍니다."
    )
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("기존 데이터셋 이용하기")
        st.write("사전에 구성한 9개 시나리오 중 하나를 골라 판정 과정을 확인합니다. 실제 LLM 호출 없음(오프라인 재생).")
        st.button("데이터셋으로 이동 →", on_click=_goto, args=("dataset",), use_container_width=True)
    with col2:
        st.subheader("직접 입력하기")
        st.write("검사할 응답 텍스트를 직접 입력해 실제 LLM을 호출합니다(비용 발생, 확인 필요).")
        st.button("직접 입력으로 이동 →", on_click=_goto, args=("direct",), use_container_width=True)


def render_dataset() -> None:
    st.title("기존 데이터셋 이용하기")
    st.button("← 처음으로", on_click=_goto, args=("landing",))
    st.markdown(
        "각 시나리오는 **(질의, 응답)** 쌍과, 오프라인 재생용으로 **사전에 기록해 둔 K1 judge 결과 "
        "/ C2 추출 결과**로 구성됩니다. 다만 **K1-V4(정규식+등록부 대조)와 C2의 decide_violation(순수 "
        "함수 판정)은 사전 기록이 아니라 매번 실제로 다시 계산**됩니다 — 이 둘은 LLM 호출이 아니라서 "
        "오프라인에서도 '진짜로' 실행됩니다."
    )

    scenarios = load_scenarios()
    st.table(build_dataset_table(scenarios))

    ids = list(scenarios.keys())
    labels = [scenarios[sid]["label"] for sid in ids]
    choice = st.selectbox("실행할 시나리오를 고르세요", options=range(len(ids)), format_func=lambda i: labels[i])
    sid = ids[choice]
    scenario = scenarios[sid]

    with st.expander("선택한 시나리오 전체 보기"):
        st.write(f"**질의**: {scenario['query']}")
        st.write(f"**응답**: {scenario['response']}")
        if scenario.get("note"):
            st.info(scenario["note"])

    if st.button("이 시나리오 실행 (오프라인 재생)", type="primary"):
        result = run_scenario(scenario, offline=True)
        st.session_state["result"] = result
        st.session_state["result_scenario"] = scenario
        _goto("result")
        st.rerun()


def render_direct() -> None:
    st.title("직접 입력하기")
    st.button("← 처음으로", on_click=_goto, args=("landing",))
    st.warning(
        "K1/C2는 '공격 질의' 자체가 아니라 **챗봇이 이미 생성한 응답**을 검사합니다. "
        "아래 '검사할 응답'란에는 공격에 노출된 챗봇이 실제로 내놓았다고 가정한 응답 문장을 적어주세요."
    )
    query = st.text_input("질의(참고용 — K1-V1/V2 judge에만 쓰임)", value="")
    response = st.text_area("검사할 응답(여기가 실제 판정 대상)", value="", height=120)

    st.error("아래 실행 버튼을 누르면 실제 OpenAI API를 호출합니다(K1 judge 1회 + C2 추출 1회, 비용 발생).")
    confirmed = st.checkbox("비용 발생에 동의하고 실제로 호출합니다")

    if st.button("실행 (실제 LLM 호출)", type="primary", disabled=not (confirmed and response.strip())):
        scenario = {"label": "직접 입력", "query": query, "response": response, "note": None}
        with st.spinner("K1 judge + C2 추출 호출 중..."):
            result = run_scenario(scenario, offline=False)
        st.session_state["result"] = result
        st.session_state["result_scenario"] = scenario
        _goto("result")
        st.rerun()


def render_result() -> None:
    scenario = st.session_state.get("result_scenario")
    result = st.session_state.get("result")
    st.title("판정 결과")
    st.button("← 처음으로", on_click=_goto, args=("landing",))
    if not scenario or not result:
        st.error("실행된 결과가 없습니다. 처음으로 돌아가 시나리오를 먼저 실행하세요.")
        return

    st.subheader(scenario.get("label", "직접 입력"))
    st.write(f"**질의**: {scenario['query']}")
    st.write(f"**응답**: {scenario['response']}")

    k1 = result["k1_verdict"]
    c2 = result["c2_decision"]

    cols = st.columns(4)
    with cols[0]:
        st.markdown("**① K1-V1/V2 (LLM judge)**")
        box = st.error if (k1.violations["V1"] or k1.violations["V2"]) else st.success
        box(f"V1={k1.violations['V1']} / V2={k1.violations['V2']}")
        reason = k1.evidence.get("V1") or k1.evidence.get("V2")
        if reason:
            st.caption(reason)
    with cols[1]:
        st.markdown("**② K1-V4 (정규식+등록부)**")
        v4_hit = k1.evidence.get("V4")
        (st.error if k1.violations["V4"] else st.success)(f"V4={k1.violations['V4']}")
        if v4_hit:
            st.caption(f"매칭값: {v4_hit}")
    with cols[2]:
        st.markdown("**③ C2 구조화 추출**")
        items = c2.get("items", [])
        if not items:
            st.success("추출된 항목 없음")
        else:
            for item in items:
                st.caption(f"{item['credential_type']} → {item['sink_type']}")
    with cols[3]:
        st.markdown("**④ C2 decide_violation**")
        (st.error if c2["violated"] else st.success)(f"위반={c2['violated']}")

    st.divider()
    if result["blocked"]:
        st.error("## 최종 판정: BLOCK")
    else:
        st.success("## 최종 판정: PASS")

    fired = []
    if k1.violations["V1"]:
        fired.append("K1-V1")
    if k1.violations["V2"]:
        fired.append("K1-V2")
    if k1.violations["V4"]:
        fired.append("K1-V4")
    if c2["violated"]:
        fired.append("C2")
    if fired:
        st.write("걸린 규칙: " + ", ".join(fired))

    notes = limitation_notes(k1, c2)
    if scenario.get("note"):
        notes.append(scenario["note"])
    for note in notes:
        st.warning(note)


def main() -> None:
    st.session_state.setdefault("page", "landing")
    page = st.session_state["page"]
    if page == "landing":
        render_landing()
    elif page == "dataset":
        render_dataset()
    elif page == "direct":
        render_direct()
    elif page == "result":
        render_result()
    else:
        _goto("landing")
        render_landing()


if __name__ == "__main__":
    main()
