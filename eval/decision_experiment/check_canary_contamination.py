"""B2(KAD) 카나리 토큰 형식 문자열이 dev/holdout 청크 내용에 우연히 섞여 있는지 검사한다.

섞여 있으면 그 청크에서는 "토큰이 응답에 그대로 나오는지"를 보는 B2 판정 자체가 무의미해진다
(청크 본문에 이미 토큰 형식 문자열이 있으면 모델이 그걸 그대로 따라 할 수도, 혼동할 수도 있다).
`docs/decision_protocol.md`의 B2 절이 요구하는 필수 사전 점검이며, 새 API 호출은 하지 않는다.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOKEN_FORMAT_RE = re.compile(r"\bVC-\d{4}\b")

DEV_FILES = [
    "eval/dataset/pilot/pilot1_normal.json",
    "eval/dataset/pilot/pilot1_injection.json",
    "eval/dataset/pilot/pilot2_boilerplate.json",
    "eval/dataset/pilot/pilot3_pairs.json",
]
HOLDOUT_FILES = [
    "eval/dataset/holdout/t0.json",
    "eval/dataset/holdout/t1.json",
    "eval/dataset/holdout/t2.json",
    "eval/dataset/holdout/t3.json",
    "eval/dataset/holdout/t4.json",
    "eval/dataset/holdout/hard_negative.json",
]


def check(paths: list[str]) -> list[tuple[str, str]]:
    hits = []
    for rel_path in paths:
        full_path = ROOT / rel_path
        if not full_path.exists():
            continue
        data = json.loads(full_path.read_text(encoding="utf-8"))
        for item in data:
            text = json.dumps(item["chunk"], ensure_ascii=False)
            if TOKEN_FORMAT_RE.search(text):
                hits.append((item["chunk_id"], rel_path))
    return hits


def main() -> int:
    dev_hits = check(DEV_FILES)
    holdout_hits = check(HOLDOUT_FILES)
    print(f"dev set 오염: {len(dev_hits)}건")
    for chunk_id, path in dev_hits:
        print(f"  - {chunk_id} ({path})")
    print(f"holdout 오염: {len(holdout_hits)}건")
    for chunk_id, path in holdout_hits:
        print(f"  - {chunk_id} ({path})")
    total = len(dev_hits) + len(holdout_hits)
    if total == 0:
        print("\n오염 없음 — B2 실행 가능.")
        return 0
    print(f"\n총 {total}건 오염 발견 — B2 실행 전에 해당 청크를 수정해야 한다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
