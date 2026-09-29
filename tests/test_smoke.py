import ast
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


BUILTIN_GENERICS = {"list", "dict", "set", "frozenset", "tuple", "type"}


def _annotation_nodes(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                yield node.returns
            a = node.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                if arg is not None and arg.annotation is not None:
                    yield arg.annotation


def find_py38_problems(source, filename="<src>"):
    """Python 3.8에서 깨지는 타입 힌트를 찾는다: list[str] 같은 내장 제네릭, X | None 유니온.

    ast.parse(feature_version=(3, 8))는 match문 같은 문법만 잡고 위 두 가지는 못 잡으므로 직접 검사한다.
    검사 대상은 타입 어노테이션이다(런타임 표현식 속 list[str]은 대상 아님).
    """
    tree = ast.parse(source, filename=filename, feature_version=(3, 8))
    problems = []
    for ann in _annotation_nodes(tree):
        for n in ast.walk(ann):
            if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                    and n.value.id in BUILTIN_GENERICS):
                problems.append("%s:%d 내장 제네릭 %s[...]" % (filename, n.lineno, n.value.id))
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr):
                problems.append("%s:%d X | Y 유니온" % (filename, n.lineno))
    return problems


@pytest.mark.parametrize("bad", [
    "x: list[str] = []",
    "def f(a: dict[str, int]): pass",
    "def f() -> str | None: pass",
    "def f(a: 'x' = None, *, b: tuple[int, ...] = ()): pass",
])
def test_guard_catches_py39_hints(bad):
    assert find_py38_problems(bad)


def test_guard_accepts_typing_hints():
    ok = "from typing import List, Optional\ndef f(a: List[str]) -> Optional[str]: pass"
    assert not find_py38_problems(ok)


def test_sources_are_python38_compatible():
    files = [p for p in ROOT.rglob("*.py") if ".venv" not in p.parts]
    assert files
    problems = []
    for p in files:
        problems += find_py38_problems(p.read_text(encoding="utf-8"), str(p.relative_to(ROOT)))
    assert not problems, problems
