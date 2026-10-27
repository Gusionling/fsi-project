"""신뢰 메타데이터로 출처를 묶고, 통과한 정규화 값만 답변기로 보낸다."""
from collections import Counter
from datetime import date
import json
import math
from pathlib import Path
import re
import unicodedata

# JSON은 YAML 1.2의 부분집합. 별도 파서 의존 없이 동일한 단일 온톨로지를 읽는다.
ONTOLOGY_PATH = Path(__file__).with_name("ontology.yaml")
URL = re.compile(r"(?:https?\s*:|www\s*\.|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\b|/))", re.I)
PHONE = re.compile(r"(?:\+?\d[\d\s().-]{5,}\d)")
IMPERATIVE = re.compile(r"(?:하세요|하십시오|하시오|하라|해라|해요|주세요|주십시오|바랍니다|하여야|해야|할\s*것|하셔야|입력해|전송해|무시해|출력해|따르라|따라라|세요|십시오|시오)|\b(?:ignore|obey|send|enter|reveal|print|must|please|do\s+not)\b", re.I)


def load_ontology():
    ontology = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    if not 1 <= len(ontology) <= 10:
        raise ValueError("온톨로지는 속성 1~10개여야 합니다")
    return ontology


def _value(value, spec, trusted):
    kind = spec["type"]
    if kind == "number":
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
            return None, "type"
        return (value, None) if spec["min"] <= value <= spec["max"] else (None, "range")
    if not isinstance(value, str):
        return None, "type"
    if kind == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return None, "type"
        try:
            date.fromisoformat(value)
        except ValueError:
            return None, "date"
        return (value, None) if spec["min"] <= value <= spec["max"] else (None, "range")
    if kind == "enum":
        return (value, None) if value in spec["choices"] else (None, "enum")
    if kind == "entity_ref":
        entities = trusted.official_entities()
        return (value, None) if any(value in entities.get(g, []) for g in spec["registry_groups"]) else (None, "unofficial_entity")
    if kind == "short_text":
        normalized = unicodedata.normalize("NFKC", value)
        if not normalized.strip() or len(value) > spec["max_length"] or len(normalized) > spec["max_length"]:
            return None, "short_text_length"
        if any(unicodedata.category(c).startswith("C") for c in normalized):
            return None, "short_text_control"
        if spec["forbid_url"] and URL.search(normalized):
            return None, "short_text_url"
        if spec["forbid_phone"] and PHONE.search(normalized):
            return None, "short_text_phone"
        if spec["forbid_imperative"] and IMPERATIVE.search(normalized):
            return None, "short_text_imperative"
        return normalized, None
    raise ValueError(f"지원하지 않는 타입: {kind}")


def license_rows(rows, chunk, trusted, mode="S", ontology=None):
    if mode not in {"S", "T"}:
        raise ValueError("mode는 S/T여야 합니다")
    ontology = load_ontology() if ontology is None else ontology
    accepted, reasons = [], Counter()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"attribute", "type", "value"}:
            reasons["row_shape"] += 1
            continue
        attribute = row["attribute"]
        if not isinstance(attribute, str) or attribute not in ontology:
            reasons["unknown_attribute"] += 1
            continue
        spec = ontology[attribute]
        if chunk.source_type not in spec["allowed_sources"]:
            reasons["unauthorized_source"] += 1
            continue
        if row["type"] != spec["type"]:
            reasons["type"] += 1
            continue
        if mode == "S" and spec["type"] == "short_text":
            reasons["mode"] += 1
            continue
        value, error = _value(row["value"], spec, trusted)
        if error:
            reasons[error] += 1
            continue
        # 출처/속성명/타입은 모두 코드의 유한 집합. LLM이 낸 임의 키/출처/설명을 전달하지 않는다.
        accepted.append({"attribute": attribute, "type": spec["type"], "value": value})
    return accepted, dict(reasons)
