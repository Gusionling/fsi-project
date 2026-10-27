"""v3 데이터 제작·검증 공용 도구 (소유자: data).

하네스(eval/v3/common)의 로더는 쓰지 않는다. 스키마 검증은 docs/validation_v3/*.schema.json 을 직접 읽어 자체 구현한다.
test_sealed 는 V3_ALLOW_SEALED=1 이 설정됐을 때만 열고, 그렇지 않으면 sealed_manifest.json(건수·분포·크기)만 본다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "eval" / "v3" / "data"
SCHEMA_DIR = ROOT / "docs" / "validation_v3"

CASE_FILES = {"dev": "cases_dev.jsonl", "calib": "cases_calib.jsonl", "test_sealed": "cases_test_sealed.jsonl"}
DONORS_FILE = "donors.jsonl"
SEALED_MANIFEST = "sealed_manifest.json"

HN_TYPES = ["policy_change", "overdue_notice", "auth_notice", "fee_waiver", "incident_report", "password_reset", "contact_info"]
INTENTS = ["acct_redirect", "external_link", "info_exfil", "prompt_leak", "false_confirmation"]
ENTITY_INTENTS = {"acct_redirect", "external_link"}
NO_ENTITY_INTENTS = {"info_exfil", "prompt_leak", "false_confirmation"}
COMPLETED_STATES = {"completed", "approved"}

# 에이전트가 직접 쓴 항목의 author_model (CONTRACT §5.3: 모델 식별자)
HAND_AUTHOR = "claude-sonnet-5-5"
HAND_AUTHORS = {HAND_AUTHOR, "claude-code-unknown"}

# 기존 V4/judge 와 같은 정규식 (eval/decision_experiment/common.py 와 동일 정의)
URL_RE = re.compile(r"https?://[^\s)\]]+")
ACCOUNT_RE = re.compile(r"\d{3,4}-\d{2,4}-\d{6,9}")
PHONE_RE = re.compile(r"\b\d{3,4}-\d{4}\b")

# 가상 데이터 규칙(R8): 실존 기관명 차단 목록. 이 단어가 나오면 lint 실패.
REAL_INSTITUTION_WORDS = [
    "국민은행", "신한은행", "신한카드", "우리은행", "하나은행", "농협", "기업은행", "산업은행", "카카오뱅크", "카카오페이", "토스뱅크", "토스페이",
    "케이뱅크", "SC제일", "씨티은행", "새마을금고", "신협", "수협", "우체국", "금융감독원", "금융위원회", "한국은행",
    "삼성카드", "현대카드", "롯데카드", "비씨카드", "네이버페이", "페이코",
]
ALLOWED_DOMAIN_SUFFIXES = ("example.com", "example.net", "example.org", ".test", ".invalid")


# ---------------------------------------------------------------------------
# 입출력
# ---------------------------------------------------------------------------


def sealed_open() -> bool:
    return os.environ.get("V3_ALLOW_SEALED") == "1"


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def write_json(path: Path, obj: Any) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_topics(data_dir: Path = DATA_DIR) -> List[Dict[str, Any]]:
    return read_json(data_dir / "topics.json")


def load_registry(data_dir: Path = DATA_DIR) -> Dict[str, List[str]]:
    ent = read_json(data_dir / "registry" / "entities.json")
    return {k: list(ent.get(k, [])) for k in ("accounts", "urls", "phones")}


def load_procedures(data_dir: Path = DATA_DIR) -> List[Dict[str, Any]]:
    return read_json(data_dir / "registry" / "procedures.json")


def load_cases(split: str, data_dir: Path = DATA_DIR) -> List[Dict[str, Any]]:
    path = data_dir / CASE_FILES[split]
    if split == "test_sealed" and not sealed_open():
        raise PermissionError("test_sealed 는 V3_ALLOW_SEALED=1 일 때만 연다. 건수·분포는 sealed_manifest.json 을 본다.")
    return read_jsonl(path) if path.exists() else []


def load_donors(data_dir: Path = DATA_DIR) -> List[Dict[str, Any]]:
    path = data_dir / DONORS_FILE
    return read_jsonl(path) if path.exists() else []


# ---------------------------------------------------------------------------
# 스키마 검증 (자체 구현)
# ---------------------------------------------------------------------------

_validators: Dict[str, Draft202012Validator] = {}


def validator(name: str) -> Draft202012Validator:
    if name not in _validators:
        _validators[name] = Draft202012Validator(read_json(SCHEMA_DIR / name))
    return _validators[name]


def schema_errors(row: Dict[str, Any], kind: str) -> List[str]:
    """kind = 'case' | 'donor'. 오류 메시지 목록(없으면 빈 리스트)."""
    v = validator("case.schema.json" if kind == "case" else "donor.schema.json")
    out = []
    for e in sorted(v.iter_errors(row), key=lambda e: list(e.path)):
        out.append(f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message[:140]}")
    return out


# ---------------------------------------------------------------------------
# 텍스트 도구
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"[^\w\s]", "", text.lower()))


def ngram_set(text: str, n: int = 5) -> Set[int]:
    s = normalize(text)
    if len(s) < n:
        return {hash(s)}
    return {hash(s[i:i + n]) for i in range(len(s) - n + 1)}


def jaccard(a: Set[int], b: Set[int]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def first_words(text: str, k: int = 6) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text).split()[:k])


def sentence_count(text: str) -> int:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text.strip())
    return len([p for p in parts if len(p.strip()) > 1])


def near_duplicate_pairs(items: Sequence[Tuple[str, str]], other: Optional[Sequence[Tuple[str, str]]] = None,
                         threshold: float = 0.8) -> List[Tuple[str, str, float]]:
    """(id, text) 목록 안(또는 두 목록 사이)에서 문자 5-gram Jaccard > threshold 인 쌍.
    정확히 같은 정규화 텍스트도 포함한다. bottom-k 스케치로 후보를 추린 뒤 정확히 검증한다."""
    K = 12

    def prep(seq):
        out = []
        for cid, text in seq:
            grams = ngram_set(text)
            sketch = sorted(grams)[:K]
            out.append((cid, normalize(text), grams, sketch))
        return out

    A = prep(items)
    B = prep(other) if other is not None else A
    index: Dict[int, List[int]] = {}
    for j, (_, _, _, sk) in enumerate(B):
        for h in sk:
            index.setdefault(h, []).append(j)
    pairs, seen = [], set()
    for i, (cid, norm, grams, sk) in enumerate(A):
        cands = set()
        for h in sk:
            cands.update(index.get(h, ()))
        for j in cands:
            if other is None and j <= i:
                continue
            if (i, j) in seen:
                continue
            seen.add((i, j))
            oid, onorm, ograms, _ = B[j]
            if cid == oid and other is not None:
                continue
            if norm == onorm:
                pairs.append((cid, oid, 1.0))
                continue
            jac = jaccard(grams, ograms)
            if jac > threshold:
                pairs.append((cid, oid, jac))
    return pairs


def entities_in(text: str) -> Dict[str, List[str]]:
    return {"accounts": ACCOUNT_RE.findall(text), "urls": URL_RE.findall(text), "phones": PHONE_RE.findall(text)}


def url_host_ok(url: str) -> bool:
    host = re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower().rstrip(".,)")
    return host.endswith(ALLOWED_DOMAIN_SUFFIXES) or host in ("example.com", "example.net", "example.org")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
