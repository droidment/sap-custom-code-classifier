"""Stage 2c: merge heuristic results and LLM batch results into work/classification.json.

Reads  work/inventory.jsonl, work/evidence.jsonl, work/auto.json, work/llm/*.json,
       optionally work/review_patch.json (with --apply-review)
Writes work/classification.json, work/merge_report.md

Validation: every LLM record must match tools/schema.json in spirit: known key, module is a
top-level taxonomy id, submodule/area are real children, confidence in [0,1], purpose non-empty.
Invalid records are reported and the object stays UNCLASSIFIED (module UNKNOWN, source 'missing')
so that a rerun picks it up.

Usage:  py tools/merge.py --config migration.config.json [--apply-review]
"""
from __future__ import annotations

import datetime as dt
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Taxonomy, base_argparser, load_config, load_taxonomy, log, read_json, read_jsonl, write_json  # noqa: E402

VALID_FLAGS = {"cross-module", "utility", "obsolete-candidate", "test-code", "mixed-fugr", "needs-human",
               "mislabeled-package", "interface", "report-only", "generated", "copy-of-standard", "dead-code"}


def normalize(rec: dict, tax: Taxonomy) -> Tuple[Optional[dict], str]:
    """Return (normalized record, error). Accepts module/submodule/area at any depth and fixes the path."""
    key = rec.get("key")
    if not key or not isinstance(key, str):
        return None, "missing key"
    module, sub, area = rec.get("module"), rec.get("submodule") or None, rec.get("area") or None
    if not module:
        return None, f"{key}: missing module"
    module = str(module).upper()
    sub = str(sub).upper() if sub else None
    area = str(area).upper() if area else None
    # deepest known node wins, then rebuild the path from the taxonomy
    deepest = None
    for cand in (area, sub, module):
        if cand and cand in tax.nodes:
            deepest = cand
            break
    if deepest is None:
        return None, f"{key}: unknown taxonomy ids module={module} submodule={sub} area={area}"
    m, s, a = tax.split(deepest)
    try:
        conf = float(rec.get("confidence", 0))
    except (TypeError, ValueError):
        return None, f"{key}: confidence not numeric"
    if not 0.0 <= conf <= 1.0:
        return None, f"{key}: confidence {conf} out of range"
    purpose = (rec.get("purpose") or "").strip()
    if not purpose:
        return None, f"{key}: empty purpose"
    flags = [str(f) for f in (rec.get("flags") or []) if str(f) in VALID_FLAGS]
    return {"key": key, "module": m, "submodule": s, "area": a, "confidence": round(conf, 2), "purpose": purpose[:300],
            "rationale": (rec.get("rationale") or "")[:600], "flags": flags}, ""


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    ap.add_argument("--apply-review", action="store_true", help="apply work/review_patch.json on top")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    tax = load_taxonomy(cfg.taxonomy_path)
    inv = read_jsonl(cfg.inventory_file)
    inv_by_key = {r["key"]: r for r in inv}
    evidence = {r["key"]: r for r in read_jsonl(cfg.evidence_file)} if cfg.evidence_file.exists() else {}

    chosen: Dict[str, dict] = {}
    errors: List[str] = []
    stats = Counter()

    if cfg.auto_file.exists():
        for rec in read_json(cfg.auto_file)["records"]:
            norm, err = normalize(rec, tax)
            if norm:
                norm["source"] = rec.get("source", "heuristic")
                chosen[norm["key"]] = norm
            else:
                errors.append("auto: " + err)

    llm_files = sorted(cfg.llm_dir.glob("*.json"), key=lambda p: p.stat().st_mtime) if cfg.llm_dir.exists() else []
    for p in llm_files:
        try:
            data = read_json(p)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{p.name}: not valid json ({exc})")
            continue
        results = data.get("results") if isinstance(data, dict) else data
        if not isinstance(results, list):
            errors.append(f"{p.name}: no 'results' list")
            continue
        model = data.get("model", "") if isinstance(data, dict) else ""
        for rec in results:
            norm, err = normalize(rec, tax)
            if not norm:
                errors.append(f"{p.name}: {err}")
                stats["llm_invalid"] += 1
                continue
            if norm["key"] not in inv_by_key:
                errors.append(f"{p.name}: {norm['key']} is not in the inventory")
                stats["llm_invalid"] += 1
                continue
            norm["source"] = "llm"
            norm["model"] = model
            norm["batch"] = p.stem
            chosen[norm["key"]] = norm   # later files (by mtime) override earlier ones
            stats["llm_valid"] += 1

    if args.apply_review and cfg.review_patch_file.exists():
        patch = read_json(cfg.review_patch_file)
        for rec in patch if isinstance(patch, list) else patch.get("results", []):
            norm, err = normalize(rec, tax)
            if not norm or norm["key"] not in inv_by_key:
                errors.append(f"review_patch: {err or norm['key'] + ' not in inventory'}")
                continue
            norm["source"] = "review"
            chosen[norm["key"]] = norm
            stats["review_applied"] += 1

    objects = []
    for rec in inv:
        k = rec["key"]
        c = chosen.get(k)
        e = evidence.get(k, {})
        if c is None:
            c = {"key": k, "module": "UNKNOWN", "submodule": None, "area": None, "confidence": 0.0,
                 "purpose": rec.get("description", ""), "rationale": "not yet classified", "flags": [], "source": "missing"}
            stats["unclassified"] += 1
        stats["source:" + c["source"]] += 1
        stats["module:" + c["module"]] += 1
        objects.append({
            "key": k, "system": rec["system"], "company": rec.get("company", ""), "type": rec["type"], "name": rec["name"],
            "package": rec["package"], "package_desc": rec.get("package_desc", ""), "description": rec.get("description", ""),
            "loc": rec.get("loc", 0), "children": rec.get("children", []), "source_hash": rec.get("source_hash"),
            "files": rec.get("files", []),
            "module": c["module"], "submodule": c["submodule"], "area": c["area"], "confidence": c["confidence"],
            "source": c["source"], "model": c.get("model", ""), "purpose": c["purpose"], "rationale": c["rationale"],
            "flags": c["flags"],
            "heuristic": {"module": e.get("module"), "submodule": e.get("submodule"), "area": e.get("area"),
                          "top": e.get("top", []), "decision": e.get("decision")},
            "evidence": [f"{s['kind']}:{s['value']}->{s['node']} ({s['weight']})" for s in e.get("signals", [])[:12]],
            "refs": e.get("refs", {}), "uses": e.get("uses", []), "used_by": e.get("used_by", []),
            "rfc_call": e.get("rfc_call", False),
        })

    out = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "systems": [{"id": s["id"], "company": s.get("company", "")} for s in cfg.systems],
        "taxonomy": tax.raw["nodes"],
        "stats": dict(stats),
        "objects": objects,
    }
    write_json(cfg.classification_file, out)

    report = ["# Merge report", "", f"Generated: {out['generated']}", "", "## Counts", ""]
    for k, v in sorted(stats.items()):
        report.append(f"- {k}: {v}")
    report += ["", f"## Validation errors ({len(errors)})", ""]
    report += [f"- {e}" for e in errors[:500]] or ["none"]
    (cfg.work_dir / "merge_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    log(f"classification: {len(objects)} objects -> {cfg.classification_file}; errors={len(errors)}")
    print(f"MERGE_OK objects={len(objects)} unclassified={stats['unclassified']} llm_valid={stats['llm_valid']} "
          f"llm_invalid={stats['llm_invalid']} errors={len(errors)} report={cfg.work_dir / 'merge_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
