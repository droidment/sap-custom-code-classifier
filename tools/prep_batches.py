"""Stage 2b: split objects into auto-classified records and LLM batches.

Reads  work/inventory.jsonl, work/evidence.jsonl
Writes work/auto.json                 heuristic classifications (decision == auto)
       work/batches/NNN.json          objects that need the LLM, with source excerpts

Options
  --limit N                 only write the first N batches (smoke test)
  --min-confidence X        re-batch objects whose current classification (work/classification.json)
                            has confidence < X; batch ids are prefixed with R (rerun)
  --only-module MOD         restrict to one module (e.g. UNKNOWN)
  --force                   rebuild batches even if work/llm results exist for them

Usage:  py tools/prep_batches.py --config migration.config.json [--limit 2]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    base_argparser, code_lines, comment_lines, load_config, load_taxonomy, log, read_json, read_jsonl,
    read_text, write_json,
)

INTERESTING = re.compile(
    r"\b(SELECT|FROM|JOIN|UPDATE|MODIFY|INSERT|DELETE|CALL\s+FUNCTION|CALL\s+METHOD|CALL\s+TRANSACTION|SUBMIT|"
    r"INFOTYPES|TABLES|INCLUDE|MESSAGE|AUTHORITY-CHECK|ENHANCEMENT|INTERFACES|INHERITING|CREATE\s+OBJECT|"
    r"REPORT|PROGRAM|FUNCTION|CLASS\s+\S+\s+DEFINITION|METHODS?|FORM\s+|GET\s+PERNR|NODES|PARAMETERS|SELECT-OPTIONS|"
    r"RP[-_]PROVIDE|RAISE|CALL\s+BADI|GET\s+BADI|OPEN\s+DATASET|TRANSFER|CL_\w+=>|NEW\s+\w+\()",
    re.IGNORECASE,
)


def excerpt_for(root: Path, rec: dict, max_lines: int, max_chars: int) -> str:
    """Header comments + declarations + the lines carrying evidence, capped."""
    parts: List[str] = []
    budget_lines = max_lines
    for relfile in rec.get("source_files", []):
        if budget_lines <= 0:
            break
        try:
            text = read_text(root / relfile)
        except OSError:
            continue
        parts.append(f"--- {relfile}")
        head = list(comment_lines(text))[:15]
        if head:
            parts.append("* " + "\n* ".join(head))
        kept = 0
        for no, line in code_lines(text):
            if kept >= budget_lines:
                parts.append("... (truncated)")
                break
            s = line.strip()
            if no <= 25 or INTERESTING.search(s):
                parts.append(f"{no:5d}  {s[:160]}")
                kept += 1
        budget_lines -= kept
    out = "\n".join(parts)
    if len(out) > max_chars:
        out = out[: max_chars - 20] + "\n... (truncated)"
    return out


def heuristic_rationale(ev: dict) -> str:
    sig = ev.get("signals", [])[:8]
    return "; ".join(f"{s['kind']}={s['value']}->{s['node']}" for s in sig) or "no evidence"


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-confidence", type=float, default=None)
    ap.add_argument("--only-module", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ccfg = cfg.classification
    tax = load_taxonomy(cfg.taxonomy_path)
    inv = {r["key"]: r for r in read_jsonl(cfg.inventory_file)}
    evidence = {r["key"]: r for r in read_jsonl(cfg.evidence_file)}
    roots = cfg.roots()
    batch_size = int(ccfg.get("batch_size", 20))

    rerun = args.min_confidence is not None
    if rerun:
        if not cfg.classification_file.exists():
            raise SystemExit("--min-confidence needs work/classification.json (run merge first)")
        cls = read_json(cfg.classification_file)
        keys = [o["key"] for o in cls["objects"] if o.get("confidence", 0) < args.min_confidence
                or o.get("module") == "UNKNOWN"]
        auto_rows: List[dict] = []
        log(f"rerun: {len(keys)} objects below confidence {args.min_confidence}")
    else:
        keys = [k for k, e in evidence.items() if e["decision"] == "needs_llm"]
        auto_rows = []
        for k, e in evidence.items():
            if e["decision"] != "auto":
                continue
            rec = inv[k]
            auto_rows.append({
                "key": k, "module": e["module"], "submodule": e["submodule"], "area": e["area"],
                "confidence": e["confidence"], "source": "heuristic+propagation" if e.get("via_propagation") else "heuristic",
                "purpose": rec.get("description") or "", "rationale": heuristic_rationale(e), "flags": [],
            })
        write_json(cfg.auto_file, {"count": len(auto_rows), "records": auto_rows})
        log(f"auto: {len(auto_rows)} -> {cfg.auto_file}")

    if args.only_module:
        keys = [k for k in keys if evidence[k]["module"] == args.only_module]

    # stable order: by system, package, name  -> batches stay identical between runs
    keys.sort(key=lambda k: (inv[k]["system"], inv[k]["package"], inv[k]["type"], inv[k]["name"]))
    cfg.batches_dir.mkdir(parents=True, exist_ok=True)
    cfg.llm_dir.mkdir(parents=True, exist_ok=True)
    existing_results = {p.stem for p in cfg.llm_dir.glob("*.json")}
    prefix = "R" if rerun else ""
    max_lines = int(ccfg.get("excerpt_max_lines", 140))
    max_chars = int(ccfg.get("excerpt_max_chars", 7000))
    taxonomy_brief = [{"id": n["id"], "name": n["name"], "parent": n.get("parent")} for n in tax.raw["nodes"]]

    written = skipped = 0
    for bi in range(0, len(keys), batch_size):
        batch_id = f"{prefix}{bi // batch_size + 1:03d}"
        if args.limit and written >= args.limit:
            break
        if batch_id in existing_results and not args.force:
            skipped += 1
            continue
        objects = []
        for k in keys[bi: bi + batch_size]:
            rec, e = inv[k], evidence[k]
            objects.append({
                "key": k, "system": rec["system"], "type": rec["type"], "name": rec["name"],
                "package": rec["package"], "package_desc": rec.get("package_desc", ""),
                "description": rec.get("description", ""), "loc": rec.get("loc", 0),
                "children": [{"name": c["name"], "description": c.get("description", "")} for c in rec.get("children", [])][:40],
                "heuristic_top": e.get("top", []), "heuristic_pick": {"module": e["module"], "submodule": e["submodule"], "area": e["area"]},
                "evidence": [f"{s['kind']}:{s['value']}->{s['node']}" for s in e.get("signals", [])[:15]],
                "refs": {kk: list(vv)[:15] for kk, vv in e.get("refs", {}).items() if kk in ("tables", "functions", "classes", "tcodes", "badis", "includes", "authobjs")},
                "uses_custom": e.get("uses", [])[:15], "used_by_custom": e.get("used_by", [])[:15],
                "excerpt": excerpt_for(roots[rec["system"]], rec, max_lines, max_chars),
            })
        write_json(cfg.batches_dir / f"{batch_id}.json", {"batch_id": batch_id, "taxonomy": taxonomy_brief, "objects": objects})
        written += 1
    total_batches = (len(keys) + batch_size - 1) // batch_size
    log(f"batches: wrote {written}, skipped {skipped} (already have results), total {total_batches}, objects {len(keys)}")
    print(f"PREP_OK needs_llm={len(keys)} batches_total={total_batches} batches_written={written} "
          f"batches_done={skipped} batch_dir={cfg.batches_dir} llm_dir={cfg.llm_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
