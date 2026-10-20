"""demo/cli_demo.py 단위 테스트. 실제 LLM 호출 없음 — 전부 가짜 클라이언트/프리셋 재생."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import demo.cli_demo as cli_demo  # noqa: E402


def load_scenario(scenario_id: str) -> dict:
    return cli_demo.load_scenarios()[scenario_id]


def test_scenarios_file_has_expected_ids():
    scenarios = cli_demo.load_scenarios()
    assert "pass_normal_transaction" in scenarios
    assert "block_all_three_phishing_url" in scenarios
    for scenario in scenarios.values():
        assert "query" in scenario and "response" in scenario
        assert "k1_judge_result" in scenario and "c2_extraction" in scenario


def test_offline_pass_normal_is_not_blocked():
    scenario = load_scenario("pass_normal_transaction")
    result = cli_demo.run_scenario(scenario, offline=True)
    assert result["blocked"] is False
    assert result["k1_verdict"].flagged is False
    assert result["c2_decision"]["violated"] is False


def test_offline_k1_v2_only_blocks_without_c2():
    scenario = load_scenario("block_k1_v2_system_prompt")
    result = cli_demo.run_scenario(scenario, offline=True)
    assert result["blocked"] is True
    assert result["k1_verdict"].violations == {"V1": False, "V2": True, "V4": False}
    assert result["c2_decision"]["violated"] is False


def test_offline_k1_v4_detects_unregistered_account_from_response_text():
    """V4는 사전 기록이 아니라 실제 응답 텍스트+등록부 대조로 매 실행마다 계산된다."""
    scenario = load_scenario("block_k1_v4_unregistered_account")
    result = cli_demo.run_scenario(scenario, offline=True)
    assert result["k1_verdict"].violations["V4"] is True
    assert result["k1_verdict"].evidence["V4"] == "999-99-999999"


def test_offline_c2_conversation_sink_blocks():
    scenario = load_scenario("block_both_v1_c2_conversation")
    result = cli_demo.run_scenario(scenario, offline=True)
    assert result["blocked"] is True
    assert result["k1_verdict"].violations["V1"] is True
    assert result["c2_decision"]["violated"] is True


def test_offline_app_screen_trust_point_passes_and_is_flagged_as_limitation():
    scenario = load_scenario("pass_c2_app_screen_legit")
    result = cli_demo.run_scenario(scenario, offline=True)
    assert result["blocked"] is False
    notes = cli_demo.limitation_notes(result["k1_verdict"], result["c2_decision"])
    assert any("신뢰 지점" in n for n in notes)


def test_offline_without_precomputed_judge_result_raises():
    scenario = {"query": "직접 입력 질의", "response": "직접 입력 응답"}
    try:
        cli_demo.run_scenario(scenario, offline=True)
        assert False, "사전 기록 없이 오프라인 실행이 되면 안 된다"
    except ValueError:
        pass


def test_live_k1_and_c2_use_injected_clients(monkeypatch, tmp_path):
    """offline=False 경로가 K1은 judge_v1_v2(→src.llm.call_llm)를, C2는 call_extractor를 실제로 거치는지 확인.
    둘 다 가짜로 주입해 네트워크 호출 없이 경로만 검증한다."""
    from src import llm

    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / ".llm_cache")

    def fake_call_extractor(response_text, model, temperature=0):
        return {
            "actual_model": model,
            "used_temperature": temperature,
            "temperature_fallback": False,
            "extraction": {"found": False, "items": []},
            "schema_error": False,
            "raw_content": "{}",
        }

    monkeypatch.setattr(cli_demo, "call_extractor", fake_call_extractor)

    def fake_chat(prompt, json_mode):
        assert json_mode is True
        return {"violated": False, "which": [], "reason": "fake judge: 위반 없음"}

    llm.set_client(llm.FakeLLMClient(chat_fn=fake_chat))
    try:
        scenario = {"query": "질의", "response": "그냥 평범한 응답입니다."}
        result = cli_demo.run_scenario(scenario, offline=False)
    finally:
        llm.set_client(None)

    assert result["blocked"] is False
    assert result["k1_verdict"].evidence["V1"] is None


def test_format_report_includes_all_four_stages():
    scenario = load_scenario("block_all_three_phishing_url")
    result = cli_demo.run_scenario(scenario, offline=True)
    report = cli_demo.format_report(scenario, result)
    assert "[1단계]" in report
    assert "[2단계]" in report
    assert "[3단계]" in report
    assert "[4단계]" in report
    assert "[최종 판정] BLOCK" in report
    assert "K1-V1" in report and "K1-V4" in report and "C2" in report
