"""config/official_registry.json 생성 — dev(파일럿 정상 90) + dev2(구 holdout) hard_negative
40건의 정상 엔티티(계좌/URL/전화번호)를 모두 모은 "공식 등록부"를 만든다.

이 등록부는 docs/decision_protocol_v2.md 초안이 정의하는 V4(b) 계산에만 쓴다 — 실제
운영에서 이런 등록부를 유지하는 비용/현실성은 평가하지 않는다는 전제(B3와 동일)를
그대로 따르며, "이상적으로 등록부가 완전하면 오탐률이 얼마나 낮아지는가"의 상한을
보는 용도다. API 호출 없음(로컬 집계).

실행: python -m eval.decision_experiment.build_official_registry
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from eval.decision_experiment.common import load_dev_set, free_text_of, ACCOUNT_RE, URL_RE, PHONE_RE  # noqa: E402


def _entities_from(items: list[dict]) -> tuple[set, set, set]:
    accounts, urls, phones = set(), set(), set()
    for it in items:
        text = free_text_of(it["schema_type"], it["chunk"])
        accounts.update(ACCOUNT_RE.findall(text))
        urls.update(URL_RE.findall(text))
        phones.update(PHONE_RE.findall(text))
    return accounts, urls, phones


def main():
    dev = load_dev_set()
    dev_normal = [d for d in dev if d["ground_truth_label"] == "normal"]

    hard_negative = json.loads(
        (ROOT / "eval" / "dataset" / "holdout" / "hard_negative.json").read_text(encoding="utf-8")
    )

    accounts, urls, phones = set(), set(), set()
    for source_items in (dev_normal, hard_negative):
        a, u, p = _entities_from(source_items)
        accounts |= a
        urls |= u
        phones |= p

    registry = {
        "_설명": (
            "dev(파일럿 정상 90건) + dev2(구 holdout) hard_negative 40건에서 추출한 정상 "
            "엔티티 전체. docs/decision_protocol_v2.md V4(b) 계산 전용 — 등록부 완전성의 "
            "상한을 보는 용도이며, 실제 운영에서 이런 등록부를 구축·유지하는 비용/현실성은 "
            "평가 대상이 아니다(B3와 동일한 전제)."
        ),
        "accounts": sorted(accounts),
        "urls": sorted(urls),
        "phones": sorted(phones),
    }
    out_path = ROOT / "config" / "official_registry.json"
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"작성 완료: {out_path} (accounts={len(accounts)}, urls={len(urls)}, phones={len(phones)})")


if __name__ == "__main__":
    main()
