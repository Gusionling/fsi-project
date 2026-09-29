import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULES = [
    "llm", "schema_filter", "decoy_bank", "extract_unexpected",
    "invariance_engine", "verdict", "spotlight", "pipeline",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module("src." + name)


def test_schema_registry_has_six_schemas():
    reg = json.loads((ROOT / "config" / "schema_registry.json").read_text(encoding="utf-8"))
    assert len(reg) == 6
    for schema_id, schema in reg.items():
        assert schema["schema_id"] == schema_id
        assert schema["fields"]
