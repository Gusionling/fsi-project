"""check_hn 으로 라벨을 내린 뒤 모자란 dev hard negative 를 독립 정상 행으로 채운다 (소유자 data).

    python eval/v3/data/add_dev_hn_rows.py [--target 15]
현재 cases_dev.jsonl 의 유형별 개수를 세어 target 에 모자란 만큼 scenarios_normal.json 의 dev 에 행을 더한다(rev2 질문 유형 적용).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import build_scenarios as S  # noqa: E402
from eval.v3.data import data_lib as D  # noqa: E402
from eval.v3.data.revise_scenarios import HN_QTYPES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=15)
    args = ap.parse_args()
    dev = D.load_cases("dev")
    have = Counter(r["normal"]["hard_negative_type"] for r in dev if r["label"] == "normal")
    path = D.DATA_DIR / "prompts" / "scenarios_normal.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    pending = Counter(r["hn_type"] for r in data["dev"] if r["sid"] not in {x["case_id"] for x in dev})
    rng = random.Random(S.SEED + 7)
    n0 = len(data["dev"])
    nxt = max(int(r["sid"].split("_")[-1]) for r in data["dev"]) + 1
    added = Counter()
    for hn in D.HN_TYPES:
        need = args.target - have[hn] - pending[hn]
        topics = S.HN_TOPICS.get(hn, S.ALL_TOPICS)
        for k in range(max(0, need)):
            topic = topics[(k + nxt) % len(topics)]
            qt = HN_QTYPES[hn][k % 3] + (f" (주제: {topic})" if hn in ("contact_info", "policy_change", "fee_waiver") else "")
            row = S.base_row(rng, f"nor_dev_{nxt:03d}", topic, hn, qt, list(S.G.DOC_TYPES), split="dev")
            row.update(status_key=None, revision="rev2", extra_notes=[])
            data["dev"].append(row)
            nxt += 1
            added[hn] += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("현재", dict(have), "→ 추가", dict(added), f"(dev 독립 행 {n0} → {len(data['dev'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
