"""v3 데이터 로더. JSON Schema 검증과 sealed 가드(CONTRACT R2)를 여기서 한다.

test_sealed 는 환경변수 V3_ALLOW_SEALED=1 일 때만 읽는다. 이 변수는 사용자만 설정한다.
가드는 파일을 열기 전에 검사하므로, 변수가 없으면 sealed 파일의 내용은 읽히지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from jsonschema import Draft202012Validator

from eval.v3.interfaces import Case, Chunk

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = ROOT / "eval" / "v3" / "data"
SCHEMA_DIR = ROOT / "docs" / "validation_v3"
CASE_FILES = {
    "dev": "cases_dev.jsonl",
    "calib": "cases_calib.jsonl",
    "test_sealed": "cases_test_sealed.jsonl",
}
DONORS_FILE = "donors.jsonl"
SEALED_ENV = "V3_ALLOW_SEALED"

PathLike = Union[str, Path]


class SealedAccessError(PermissionError):
    pass


def sealed_allowed() -> bool:
    return os.environ.get(SEALED_ENV) == "1"


def assert_sealed_allowed(what: str) -> None:
    if not sealed_allowed():
        raise SealedAccessError(
            f"{what}: test_sealed 는 {SEALED_ENV}=1 일 때만 읽을 수 있습니다 (이 변수는 사용자만 설정합니다)."
        )


def _is_sealed_path(path: PathLike) -> bool:
    return "sealed" in Path(path).name.lower()


def file_sha256(path: PathLike) -> str:
    if _is_sealed_path(path):
        assert_sealed_allowed(f"file_sha256({Path(path).name})")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _validator(schema_name: str, schema_dir: Optional[PathLike] = None) -> Draft202012Validator:
    path = Path(schema_dir or SCHEMA_DIR) / schema_name
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _read_jsonl(path: Path, validator: Draft202012Validator) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{lineno}: JSON 파싱 실패: {exc}") from None
            errors = sorted(validator.iter_errors(row), key=lambda e: list(e.path))
            if errors:
                e = errors[0]
                where = "/".join(str(p) for p in e.path) or "(root)"
                raise ValueError(f"{path.name}:{lineno} (case_id={row.get('case_id') or row.get('chunk_id')}): "
                                 f"스키마 위반 at {where}: {e.message}")
            rows.append(row)
    return rows


def split_path(split: str, data_dir: Optional[PathLike] = None) -> Path:
    if split not in CASE_FILES:
        raise ValueError(f"알 수 없는 split: {split!r} (dev | calib | test_sealed)")
    return Path(data_dir or DEFAULT_DATA_DIR) / CASE_FILES[split]


def row_to_case(row: Dict[str, Any]) -> Case:
    return Case(
        case_id=row["case_id"],
        split=row["split"],
        label=row["label"],
        query=row["query"],
        topic=row["topic"],
        chunks=[Chunk(c["chunk_id"], c["text"], c["role"], c.get("source_type")) for c in row["chunks"]],
        attack=row.get("attack"),
        normal=row.get("normal"),
        integrity=row.get("integrity"),
        trusted_fixture=row.get("trusted_fixture") or {},
        author_model=row["author_model"],
        raw=row,
    )


def load_cases(split: str, data_dir: Optional[PathLike] = None, schema_dir: Optional[PathLike] = None) -> List[Case]:
    """split 의 케이스를 스키마 검증 후 반환한다. test_sealed 는 V3_ALLOW_SEALED=1 일 때만."""
    if split == "test_sealed":
        assert_sealed_allowed("load_cases('test_sealed')")
    path = split_path(split, data_dir)
    if not path.exists():
        raise FileNotFoundError(f"{path} 가 없습니다 (data 브랜치가 아직 머지되지 않았을 수 있습니다).")
    rows = _read_jsonl(path, _validator("case.schema.json", schema_dir))
    seen = set()
    for r in rows:
        if r["split"] != split:
            raise ValueError(f"{path.name}: case_id={r['case_id']} 의 split={r['split']!r} 가 파일의 split={split!r} 와 다릅니다.")
        if r["case_id"] in seen:
            raise ValueError(f"{path.name}: case_id 중복: {r['case_id']}")
        seen.add(r["case_id"])
    return [row_to_case(r) for r in rows]


def load_donors(split: str, data_dir: Optional[PathLike] = None, schema_dir: Optional[PathLike] = None) -> List[Dict[str, Any]]:
    """donors.jsonl 에서 donor split(dev | calib) 의 행만 반환한다."""
    if split not in ("dev", "calib"):
        raise ValueError(f"donor split 은 dev | calib 입니다: {split!r}")
    path = Path(data_dir or DEFAULT_DATA_DIR) / DONORS_FILE
    if not path.exists():
        raise FileNotFoundError(f"{path} 가 없습니다.")
    rows = _read_jsonl(path, _validator("donor.schema.json", schema_dir))
    ids = [r["chunk_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: chunk_id 중복이 있습니다.")
    return [r for r in rows if r["split"] == split]
