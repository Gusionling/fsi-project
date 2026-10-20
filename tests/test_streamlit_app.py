"""demo/streamlit_app.py의 순수 로직 단위 테스트. st.* UI 호출은 streamlit 런타임 없이는
실행할 수 없으므로, UI와 분리된 build_dataset_table만 테스트한다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.streamlit_app import build_dataset_table  # noqa: E402
from demo.cli_demo import load_scenarios  # noqa: E402


def test_build_dataset_table_covers_all_scenarios():
    scenarios = load_scenarios()
    rows = build_dataset_table(scenarios)
    assert len(rows) == len(scenarios)
    assert {"id", "라벨", "질의", "응답(일부)"} <= set(rows[0].keys())


def test_build_dataset_table_truncates_long_response():
    scenarios = {"x": {"label": "l", "query": "q", "response": "가" * 100}}
    rows = build_dataset_table(scenarios)
    assert rows[0]["응답(일부)"].endswith("…")
    assert len(rows[0]["응답(일부)"]) == 41


def test_build_dataset_table_keeps_short_response_as_is():
    scenarios = {"x": {"label": "l", "query": "q", "response": "짧은 응답"}}
    rows = build_dataset_table(scenarios)
    assert rows[0]["응답(일부)"] == "짧은 응답"
