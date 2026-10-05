"""사람이 직접 작성한 공격 데이터(human_written.json)의 로더/검증 스크립트.

protocol-frozen-v1의 코드 동결 대상이 아니다(탐지기 점수 계산을 건드리지 않는 데이터
검증 도구). eval/dataset/holdout/human_written_template.json의 가이드를 따라 작성된
파일이 다른 홀드아웃 데이터와 같은 전제(스키마 준수, 엔티티 비중복, 실존 브랜드명 금지,
카나리 오염 없음)를 지키는지 확인한다.

사용법:
  python -m eval.decision_experiment.validate_human_written <파일경로>
  (기본값: eval/dataset/holdout/human_written.json)
"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from eval.decision_experiment.common import SCHEMA_REGISTRY, free_text_of, ACCOUNT_RE, URL_RE, PHONE_RE  # noqa: E402

VALID_LABELS = {"normal", "naive_injection", "optimized_injection"}
VALID_INTENTS = {"acct_redirect", "external_link", "prompt_leak", "info_exfil", "false_confirmation"}
ALLOWED_URL_DOMAINS_RE = re.compile(r"^https?://[^/]*\.example\.(com|net|org)(/|$)")
CANARY_RE = re.compile(r"\bVC-\d{4}\b")

# decision_protocol.md 1.5절의 ATTACK_CLASS_INSTRUCTION_RE와 동일(실제 데이터 생성 스크립트 기준).
INSTRUCTION_SENTENCE_RE = re.compile(
    r"(하라|하십시오|하세요|바랍니다)[.!]?\s*$"
    r"|해야\s*(한다|합니다)"
    r"|하는\s*것이\s*원칙"
    r"|하도록\s*되어\s*있(다|습니다)"
    r"|[가이]\s*원칙(이다|입니다)"
)

# 실존 브랜드명 금지 체크용 — 전수 목록이 아니라 흔히 실수로 등장하는 주요 금융사만 간단히 검사한다.
REAL_BRAND_KEYWORDS = [
    "국민은행", "신한은행", "우리은행", "하나은행", "농협은행", "기업은행", "카카오뱅크",
    "토스뱅크", "케이뱅크", "신한카드", "삼성카드", "현대카드", "KB국민", "NH농협",
]


def classify_attack_class(text: str) -> str:
    sentences = [s.strip() for s in re.split(r"[.?!\n]", text) if s.strip()]
    for s in sentences:
        if INSTRUCTION_SENTENCE_RE.search(s):
            return "instruction_injection"
    return "content_poisoning"


def load_human_written(path: Path) -> list[dict]:
    """"_README" 안내 엔트리를 건너뛰고 실제 데이터 entry만 반환한다."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: 최상위가 배열이 아니다")
    return [it for it in raw if "_README" not in it]


_SKIP_FILENAMES = {"human_written.json", "human_written_template.json"}


def _existing_entities() -> tuple[set, set]:
    accounts, urls = set(), set()
    paths = list(glob.glob(str(ROOT / "eval/dataset/holdout/*.json"))) + list(
        glob.glob(str(ROOT / "eval/dataset/pilot/*.json"))
    )
    for f in paths:
        if Path(f).name in _SKIP_FILENAMES:
            continue
        for it in json.loads(Path(f).read_text(encoding="utf-8")):
            t = free_text_of(it["schema_type"], it["chunk"])
            accounts.update(ACCOUNT_RE.findall(t))
            urls.update(URL_RE.findall(t))
    return accounts, urls


def _check_schema_fields(schema_type: str, chunk: dict) -> list[str]:
    errors = []
    if schema_type not in SCHEMA_REGISTRY:
        return [f"알 수 없는 schema_type: {schema_type}"]
    fields = SCHEMA_REGISTRY[schema_type]["fields"]
    for fname, spec in fields.items():
        if fname not in chunk:
            errors.append(f"chunk에 필드 누락: {fname}")
            continue
        value = chunk[fname]
        pattern = spec.get("pattern")
        if pattern and not re.match(pattern, str(value)):
            errors.append(f"{fname}={value!r} 가 패턴 {pattern!r} 과 불일치")
        enum = spec.get("enum")
        if enum and value not in enum:
            errors.append(f"{fname}={value!r} 가 허용값 {enum} 에 없음")
    return errors


def validate_items(items: list[dict], *, is_template: bool, existing_accounts: set, existing_urls: set) -> list[str]:
    errors = []
    seen_ids = set()
    for idx, it in enumerate(items):
        prefix = f"[{idx}] chunk_id={it.get('chunk_id')!r}"
        cid = it.get("chunk_id")
        if not cid or not isinstance(cid, str):
            errors.append(f"{prefix}: chunk_id 누락/타입 오류")
        elif cid in seen_ids:
            errors.append(f"{prefix}: chunk_id 중복")
        else:
            seen_ids.add(cid)

        if not is_template and cid and cid.startswith("example_"):
            errors.append(f"{prefix}: 템플릿 예시(example_*)가 실제 파일에 그대로 남아 있다 — 지우거나 교체하라")

        if it.get("tier") != "human_written":
            errors.append(f"{prefix}: tier는 'human_written' 이어야 한다 (현재: {it.get('tier')!r})")

        label = it.get("ground_truth_label")
        if label not in VALID_LABELS:
            errors.append(f"{prefix}: ground_truth_label이 {VALID_LABELS} 중 하나가 아니다 (현재: {label!r})")

        schema_type = it.get("schema_type")
        chunk = it.get("chunk")
        if not isinstance(chunk, dict):
            errors.append(f"{prefix}: chunk가 dict가 아니다")
        else:
            errors.extend(f"{prefix}: {e}" for e in _check_schema_fields(schema_type, chunk))

        is_injection = label in ("naive_injection", "optimized_injection")
        if is_injection:
            if it.get("intent") not in VALID_INTENTS:
                errors.append(f"{prefix}: injection이면 intent가 {VALID_INTENTS} 중 하나여야 한다")
            if not isinstance(it.get("scope_marker"), bool):
                errors.append(f"{prefix}: injection이면 scope_marker(bool)가 필요하다")

        if isinstance(chunk, dict) and schema_type in SCHEMA_REGISTRY:
            text = free_text_of(schema_type, chunk)

            if CANARY_RE.search(text):
                errors.append(f"{prefix}: 카나리 토큰 형식 문자열(VC-####)이 우연히 포함되어 있다")

            for brand in REAL_BRAND_KEYWORDS:
                if brand in text:
                    errors.append(f"{prefix}: 실존 브랜드명으로 보이는 문자열 포함: {brand!r}")

            for acc in ACCOUNT_RE.findall(text):
                if acc in existing_accounts:
                    errors.append(f"{prefix}: 계좌번호 {acc!r}가 기존 pilot/holdout 데이터와 겹친다")
            for url in URL_RE.findall(text):
                bare = url.rstrip(".,)]")
                if not ALLOWED_URL_DOMAINS_RE.match(bare):
                    errors.append(f"{prefix}: URL {url!r}이 example.com/net/org 예약 도메인이 아니다")
                if url in existing_urls:
                    errors.append(f"{prefix}: URL {url!r}이 기존 pilot/holdout 데이터와 겹친다")

            if is_injection and not it.get("attack_class"):
                errors.append(
                    f"{prefix}: attack_class 비어 있음 — 자동 계산값 참고: {classify_attack_class(text)!r} "
                    "(직접 채우거나 이 값을 그대로 써도 된다)"
                )
            elif is_injection and it.get("attack_class"):
                auto = classify_attack_class(text)
                if it["attack_class"] != auto:
                    errors.append(
                        f"{prefix}: attack_class={it['attack_class']!r} 가 1.5절 규칙 자동 계산값 "
                        f"{auto!r} 과 다르다 — 의도한 것이 맞는지 확인하라(에러는 아니고 참고용 경고)"
                    )

    return errors


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval" / "dataset" / "holdout" / "human_written.json"
    is_template = target.name == "human_written_template.json"
    if not target.exists():
        print(f"{target} 가 없다.")
        return 1

    items = load_human_written(target)
    print(f"{target} 로드: {len(items)}건 (_README 제외)")

    existing_accounts, existing_urls = _existing_entities()
    errors = validate_items(items, is_template=is_template, existing_accounts=existing_accounts, existing_urls=existing_urls)

    if not errors:
        print("검증 통과: 위반 0건")
        return 0
    print(f"검증 결과: {len(errors)}건 발견(attack_class 참고성 경고 포함)")
    for e in errors:
        print(" -", e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
