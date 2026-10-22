"""Print the pending LLM batches and the per-run limit (used by the /classify command).

Usage:  py tools/pending.py --config migration.config.json
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    batches = {p.stem for p in cfg.batches_dir.glob("*.json")} if cfg.batches_dir.exists() else set()
    done = {p.stem for p in cfg.llm_dir.glob("*.json")} if cfg.llm_dir.exists() else set()
    pending = sorted(batches - done)
    per_run = int(cfg.classification.get("batches_per_run", 10))
    this_run = pending[:per_run]
    print(f"PENDING total={len(pending)} done={len(done)} batches_per_run={per_run}")
    print("THIS_RUN " + (" ".join(this_run) if this_run else "none"))
    print("REMAINING_AFTER_THIS_RUN " + str(max(0, len(pending) - len(this_run))))
    for b in this_run:
        print(f"  {cfg.batches_dir / (b + '.json')}  ->  {cfg.llm_dir / (b + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
