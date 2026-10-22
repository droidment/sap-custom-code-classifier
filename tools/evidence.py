"""Stage 2a: extract evidence from every object, score it against the taxonomy, propagate
through the custom-code dependency graph and decide auto vs needs_llm.

Reads  work/inventory.jsonl
Writes work/evidence.jsonl   (one record per object, same order as inventory)

Usage:  py tools/evidence.py --config migration.config.json
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    Taxonomy, base_argparser, code_lines, comment_lines, load_config, load_taxonomy, log,
    make_key, read_jsonl, read_text, split_key, write_jsonl,
)

# --------------------------------------------------------------------------------------
# Regexes for ABAP evidence extraction (applied to comment-free code lines, upper-cased)
# --------------------------------------------------------------------------------------
NAME = r"([A-Z0-9_/]+)"
RX = {
    "select_from": re.compile(r"\bFROM\s+" + NAME),
    "join": re.compile(r"\bJOIN\s+" + NAME),
    "update": re.compile(r"\bUPDATE\s+" + NAME + r"\b(?!\s+(?:SCREEN|TABLE))"),
    "modify": re.compile(r"\bMODIFY\s+(?!TABLE\b|SCREEN\b|LINE\b|CURRENT\b)" + NAME),
    "delete_from": re.compile(r"\bDELETE\s+FROM\s+" + NAME),
    "insert_into": re.compile(r"\bINSERT\s+(?:INTO\s+)?" + NAME + r"\s+(?:FROM|VALUES|CLIENT)"),
    "tables": re.compile(r"^\s*TABLES\s*:?\s*([A-Z0-9_/ ,]+)\."),
    "type_ref": re.compile(r"\b(?:TYPE|LIKE)\s+(?:(?:STANDARD|SORTED|HASHED)\s+)?(?:TABLE\s+OF\s+|LINE\s+OF\s+|RANGE\s+OF\s+)?" + NAME),
    "ref_to": re.compile(r"\bREF\s+TO\s+" + NAME),
    "call_function": re.compile(r"\bCALL\s+FUNCTION\s+'([^']+)'"),
    "destination": re.compile(r"\bCALL\s+FUNCTION\s+'[^']+'\s+(?:DESTINATION|STARTING\s+NEW\s+TASK|IN\s+BACKGROUND\s+TASK)"),
    "static_call": re.compile(r"\b([A-Z0-9_/]+)=>"),
    "create_object": re.compile(r"\bCREATE\s+OBJECT\s+[A-Z0-9_\-<>]+\s+TYPE\s+" + NAME),
    "new": re.compile(r"\bNEW\s+" + NAME + r"\s*\("),
    "inheriting": re.compile(r"\bINHERITING\s+FROM\s+" + NAME),
    "interfaces": re.compile(r"^\s*INTERFACES\s*:?\s*" + NAME),
    "include": re.compile(r"^\s*INCLUDE\s+" + NAME + r"\s*\."),
    "submit": re.compile(r"\bSUBMIT\s+" + NAME),
    "call_transaction": re.compile(r"\b(?:CALL|LEAVE\s+TO)\s+TRANSACTION\s+'([A-Z0-9_/]+)'"),
    "message_id": re.compile(r"\bMESSAGE(?:-ID|\s+ID)\s+'?([A-Z0-9_/]+)'?"),
    "message_inline": re.compile(r"\bMESSAGE\s+[AEIWSX]\d{3}\(([A-Z0-9_/]+)\)"),
    "infotypes": re.compile(r"^\s*INFOTYPES\s*:?\s*([0-9, ]+)"),
    "p_struct": re.compile(r"\b(?:TYPE|LIKE)\s+(?:TABLE\s+OF\s+)?P(\d{4})\b"),
    "nodes": re.compile(r"^\s*NODES\s*:?\s*" + NAME),
    "get_pernr": re.compile(r"\bGET\s+(PERNR|PAYROLL|OBJEC|PERAS|GROUP)\b"),
    "rp_macro": re.compile(r"\b(RP[-_]PROVIDE[-_]FROM[-_]LAST|RP[-_]PROVIDE[-_]FROM[-_]FRST|RP[-_]READ[-_]INFOTYPE|RP[-_]UPDATE)\b"),
    "authority": re.compile(r"\bAUTHORITY-CHECK\s+OBJECT\s+'([A-Z0-9_/]+)'"),
    "enhancement_point": re.compile(r"\bENHANCEMENT-POINT\s+" + NAME + r"\s+SPOTS\s+" + NAME),
    "enhancement_impl": re.compile(r"^\s*ENHANCEMENT\s+\d+\s+" + NAME),
    "badi_get": re.compile(r"\bGET\s+BADI\s+[A-Z0-9_]+\s*(?:TYPE\s+" + NAME + r")?"),
    "ldb_report": re.compile(r"^\s*REPORT\s+[A-Z0-9_/]+.*?\bMESSAGE-ID\s+" + NAME),
    "function_def": re.compile(r"^\s*FUNCTION\s+" + NAME + r"\s*\."),
}
# Variable-name prefixes that look like tables but are not (LT_, GT_, LS_, ...)
VAR_PREFIX = re.compile(r"^(?:[LGICRSPTEM][TSVOIRCFEA]_|LT_|GT_|LS_|GS_|LV_|GV_|LO_|GO_|LR_|GR_|LC_|GC_|IT_|IS_|IV_|ET_|ES_|EV_|CT_|CS_|CV_|RT_|RS_|RV_|LTR_|FS_|WA_|ITAB|<)")
IGNORED_TOKENS = {"TABLE", "DATA", "SCREEN", "DATABASE", "INDEX", "LINE", "VALUE", "STANDARD", "SORTED", "HASHED",
                  "ANY", "C", "I", "N", "P", "D", "T", "F", "X", "STRING", "XSTRING", "DECFLOAT16", "DECFLOAT34",
                  "INT1", "INT2", "INT4", "INT8", "CHAR", "NUMC", "DATS", "TIMS", "ABAP_BOOL", "SY", "SYST", "SYMSG",
                  "OBJECT", "REF", "TO", "ME", "SUPER", "ZCX_ROOT", "CX_ROOT", "CX_STATIC_CHECK", "CX_DYNAMIC_CHECK",
                  "CX_NO_CHECK", "TYPE", "ICON", "SPACE", "ABAP_TRUE", "ABAP_FALSE", "SIMPLE", "CLIKE", "CSEQUENCE",
                  "NUMERIC", "XSEQUENCE", "BOOLEAN", "FLAG", "CHAR1", "CHAR10", "CHAR20", "CHAR30", "CHAR40",
                  "TEXT", "TIMESTAMP", "TIMESTAMPL", "SY-", "ABAP_CHAR", "ANY TABLE"}


def _clean(tok: str) -> Optional[str]:
    tok = tok.strip().upper().rstrip(".,")
    if not tok or tok in IGNORED_TOKENS or VAR_PREFIX.match(tok) or tok.startswith("<") or tok[0].isdigit():
        return None
    if tok.startswith("SY-") or "-" in tok:
        return None
    return tok


def extract_refs(text: str) -> Dict[str, Counter]:
    """Return counters of raw references by kind for one ABAP source text."""
    refs: Dict[str, Counter] = defaultdict(Counter)
    for _, line in code_lines(text):
        u = line.upper()
        for kind in ("select_from", "join", "update", "modify", "delete_from", "insert_into"):
            for m in RX[kind].finditer(u):
                t = _clean(m.group(1))
                if t:
                    refs["tables"][t] += 1
        m = RX["tables"].match(u)
        if m:
            for t in m.group(1).split(","):
                t = _clean(t)
                if t:
                    refs["tables"][t] += 1
        for m in RX["type_ref"].finditer(u):
            t = _clean(m.group(1))
            if t:
                refs["types"][t] += 1
        for m in RX["ref_to"].finditer(u):
            t = _clean(m.group(1))
            if t:
                refs["classes"][t] += 1
        for m in RX["call_function"].finditer(u):
            refs["functions"][m.group(1).upper()] += 1
        if RX["destination"].search(u):
            refs["flags"]["RFC_CALL"] += 1
        for kind in ("static_call", "create_object", "new", "inheriting"):
            for m in RX[kind].finditer(u):
                t = _clean(m.group(1))
                if t:
                    refs["classes"][t] += 1
        m = RX["interfaces"].match(u)
        if m:
            t = _clean(m.group(1))
            if t:
                refs["classes"][t] += 1
                if t.startswith("IF_EX_"):
                    refs["badis"][t[6:]] += 1
                if t in ("IF_WORKFLOW", "BI_OBJECT", "BI_PERSISTENT"):
                    refs["flags"]["WORKFLOW_OBJECT"] += 1
                if t.startswith("/IWBEP/") or t.startswith("/IWFND/"):
                    refs["flags"]["GATEWAY"] += 1
        m = RX["include"].match(u)
        if m:
            refs["includes"][m.group(1)] += 1
        for m in RX["submit"].finditer(u):
            t = _clean(m.group(1))
            if t:
                refs["submits"][t] += 1
        for m in RX["call_transaction"].finditer(u):
            refs["tcodes"][m.group(1)] += 1
        for kind in ("message_id", "message_inline", "ldb_report"):
            for m in RX[kind].finditer(u):
                refs["msgclasses"][m.group(1).upper()] += 1
        m = RX["infotypes"].match(u)
        if m:
            for it in m.group(1).split(","):
                it = it.strip()
                if it.isdigit() and len(it) == 4:
                    refs["infotypes"][it] += 1
        for m in RX["p_struct"].finditer(u):
            refs["infotypes"][m.group(1)] += 1
        m = RX["nodes"].match(u)
        if m:
            refs["ldb_nodes"][m.group(1)] += 1
        for m in RX["get_pernr"].finditer(u):
            refs["ldb_nodes"][m.group(1)] += 1
        if RX["rp_macro"].search(u):
            refs["flags"]["HR_MACRO"] += 1
        for m in RX["authority"].finditer(u):
            refs["authobjs"][m.group(1)] += 1
        for m in RX["enhancement_point"].finditer(u):
            refs["badis"][m.group(2)] += 1
        for m in RX["enhancement_impl"].finditer(u):
            refs["enhancements"][m.group(1)] += 1
        for m in RX["badi_get"].finditer(u):
            if m.group(1):
                refs["badis"][m.group(1)] += 1
        m = RX["function_def"].match(u)
        if m:
            refs["defines_functions"][m.group(1)] += 1
    return refs


def refs_from_inventory(rec: dict) -> Dict[str, Counter]:
    """Evidence that lives in the object xml rather than in ABAP source."""
    refs: Dict[str, Counter] = defaultdict(Counter)
    x = rec.get("refs", {}) or {}
    for tag in ("SPOT_NAME", "BADI_DEF", "EXIT_NAME", "ENHSPOTCOMPOSITE"):
        for v in x.get(tag, []):
            refs["badis"][v] += 1
    for tag in ("PROGRAM", "PGMNA", "INCLUDE"):
        for v in x.get(tag, []):
            refs["includes"][v] += 1
    for tag in ("CLSNAME", "IMPL_CLASS", "SUPERCLASS", "REFCLSNAME", "INTERFACE"):
        for v in x.get(tag, []):
            refs["classes"][v] += 1
    for tag in ("TABNAME", "CHECKTABLE", "SELMETHOD", "ROWTYPE", "ROLLNAME"):
        for v in x.get(tag, []):
            refs["types"][v] += 1
    for v in x.get("FUNCNAME", []):
        refs["functions"][v] += 1
    for v in x.get("TRANSACTION", []) + x.get("TCODE", []):
        refs["tcodes"][v] += 1
    ldb = (rec.get("extra") or {}).get("ldb")
    if ldb:
        refs["ldb"][ldb.upper()] += 1
    for f in (rec.get("extra") or {}).get("fields", []):
        if f.get("checktable"):
            refs["types"][f["checktable"].upper()] += 1
        if f.get("rollname"):
            refs["types"][f["rollname"].upper()] += 1
    for tok in (rec.get("extra") or {}).get("xml_tokens", []):
        refs["xml_tokens"][tok] += 1
    return refs


def merge_counters(a: Dict[str, Counter], b: Dict[str, Counter]) -> Dict[str, Counter]:
    out: Dict[str, Counter] = defaultdict(Counter)
    for src in (a, b):
        for k, c in src.items():
            out[k].update(c)
    return out


# --------------------------------------------------------------------------------------
# Rule index and scoring
# --------------------------------------------------------------------------------------
class RuleIndex:
    """Fast lookup from a signal value to (node, kind, rule_weight) hits."""

    def __init__(self, tax: Taxonomy):
        self.tax = tax
        self.exact: Dict[str, Dict[str, List[Tuple[str, float]]]] = defaultdict(lambda: defaultdict(list))
        self.prefix: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)  # kind -> [(prefix, node, w)]
        self.ranges: List[Tuple[str, str, str, float]] = []  # (lo, hi, node, w)
        self.keywords: List[Tuple[str, str, float]] = []
        for r in tax.rules:
            node, w = r["node"], float(r.get("weight", 1.0))
            for kind, vals in r.items():
                if kind in ("node", "weight") or not isinstance(vals, list):
                    continue
                if kind == "infotype_range":
                    for lo, hi in vals:
                        self.ranges.append((lo, hi, node, w))
                elif kind == "keyword":
                    for v in vals:
                        self.keywords.append((v.lower(), node, w))
                elif kind.endswith("_prefix"):
                    base = kind[: -len("_prefix")]
                    for v in vals:
                        self.prefix[base].append((v.upper(), node, w))
                else:
                    for v in vals:
                        self.exact[kind][v.upper()].append((node, w))
        for k in self.prefix:
            self.prefix[k].sort(key=lambda t: -len(t[0]))

    def hits(self, kind: str, value: str) -> List[Tuple[str, str, float]]:
        """Return [(node, matched_kind, rule_weight)] for an exact or prefix match."""
        out = []
        v = value.upper()
        for node, w in self.exact.get(kind, {}).get(v, []):
            out.append((node, kind, w))
        seen_nodes = {o[0] for o in out}
        for pfx, node, w in self.prefix.get(kind, []):
            if v.startswith(pfx) and node not in seen_nodes:
                out.append((node, kind + "_prefix", w))
                seen_nodes.add(node)
        return out

    def infotype_hits(self, it: str) -> List[Tuple[str, str, float]]:
        out = [(n, "infotype", w) for n, w in self.exact.get("infotype", {}).get(it, [])]
        seen = {o[0] for o in out}
        for lo, hi, node, w in self.ranges:
            if lo <= it <= hi and node not in seen:
                out.append((node, "infotype_range", w))
                seen.add(node)
        return out


def diminishing(n: int) -> float:
    """1 for the first occurrence, +0.25 per extra occurrence, capped at 2.0 total."""
    return min(2.0, 1.0 + 0.25 * max(0, n - 1))


# Map from refs-kind to taxonomy signal kinds to try, in order
REF_TO_KINDS = {
    "tables": ["table"],
    "types": ["table", "type_ref"],      # structures used as types (P0001, EKKO as TYPE) count as weaker table refs
    "functions": ["function"],
    "classes": ["class", "badi"],       # IF_EX_* interfaces are matched as badi too
    "includes": ["include"],
    "submits": ["include"],
    "tcodes": ["tcode"],
    "msgclasses": ["msgclass"],
    "authobjs": ["authobj"],
    "badis": ["badi"],
    "enhancements": ["badi"],
    "ldb": ["ldb"],
    "xml_tokens": ["table", "function", "class", "badi"],
}
LDB_NODE_HINT = {"PERNR": "PNP", "PAYROLL": "PNPCE", "OBJEC": "PCH", "PERAS": "PNPCE", "GROUP": "PNPCE"}


def score_object(rec: dict, refs: Dict[str, Counter], idx: RuleIndex, weights: Dict[str, float],
                 text_blob: str) -> Tuple[Dict[str, float], List[dict]]:
    scores: Dict[str, float] = defaultdict(float)
    signals: List[dict] = []

    tax = idx.tax

    def add(node: str, kind: str, value: str, count: int, rule_w: float, base_kind: Optional[str] = None, split: int = 1):
        w = weights.get(kind, weights.get(base_kind or kind, 1.0)) * rule_w * diminishing(count) / max(1, split)
        scores[node] += w
        signals.append({"kind": kind, "value": value, "node": node, "weight": round(w, 2), "count": count})

    def add_hits(hits: List[Tuple[str, str, float]], value: str, count: int, kind_override: Optional[str] = None,
                 base_kind: Optional[str] = None, rw_factor: float = 1.0):
        """Credit one signal value. Within one module, keep only the deepest node of each ancestor chain and
        split the weight between sibling branches, so a table listed on a node and its children counts once."""
        by_module: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)
        for node, mkind, rw in hits:
            by_module[tax.module_of(node)].append((node, mkind, rw))
        for module, group in by_module.items():
            nodes = {n for n, _, _ in group}
            deepest = [(n, k, rw) for n, k, rw in group if not any(n in tax.ancestors(o) and o != n for o in nodes)]
            for node, mkind, rw in deepest:
                add(node, kind_override or mkind, value, count, rw * rw_factor, base_kind=base_kind, split=len(deepest))

    for ref_kind, kinds in REF_TO_KINDS.items():
        for value, count in refs.get(ref_kind, {}).items():
            for kind in kinds:
                hits = idx.hits(kind, value)
                if hits:
                    # structures used as TYPE count as weaker table references
                    override = "type_ref" if (ref_kind == "types" and kind == "table") else None
                    add_hits(hits, value, count, kind_override=override, base_kind=kind,
                             rw_factor=0.6 if ref_kind == "xml_tokens" else 1.0)
                    break
            # PAnnnn / PBnnnn tables and Pnnnn structures also imply an infotype
            m = re.match(r"^P[AB]?(\d{4})$", value)
            if m and ref_kind in ("tables", "types"):
                add_hits(idx.infotype_hits(m.group(1)), m.group(1), count)
    for it, count in refs.get("infotypes", {}).items():
        add_hits(idx.infotype_hits(it), it, count)
    for ldb_node, count in refs.get("ldb_nodes", {}).items():
        ldb = LDB_NODE_HINT.get(ldb_node)
        if ldb:
            add_hits(idx.hits("ldb", ldb), ldb, count)
    if refs.get("flags", {}).get("HR_MACRO"):
        add_hits(idx.hits("ldb", "PNP"), "RP_MACRO", 1, kind_override="ldb", rw_factor=0.7)
    if refs.get("flags", {}).get("WORKFLOW_OBJECT"):
        add("BC-WF", "class", "IF_WORKFLOW", 1, 1.0)
    if refs.get("flags", {}).get("GATEWAY"):
        add("BC-ESI", "class", "/IWBEP/ interface", 1, 1.0)
    # name / package / description / comments
    name = rec["name"]
    for pfx, node, rw in idx.prefix.get("name", []):
        if name.startswith(pfx):
            add(node, "name_prefix", pfx, 1, rw)
            break
    for child in rec.get("children", []):
        for pfx, node, rw in idx.prefix.get("name", []):
            if child["name"].startswith(pfx):
                add(node, "name_prefix", child["name"], 1, rw * 0.5)
                break
    pkg_blob = (rec.get("package", "") + " " + rec.get("package_desc", "")).upper()
    for r in idx.tax.rules:
        for kw in r.get("package_keyword", []):
            if re.search(r"(?<![A-Z])" + re.escape(kw.upper()) + r"(?![A-Z])", pkg_blob):
                add(r["node"], "package_keyword", kw, 1, float(r.get("weight", 1.0)))
    low = text_blob.lower()
    for kw, node, rw in idx.keywords:
        if kw in low:
            add(node, "keyword", kw, low.count(kw), rw)
    add_hits(idx.hits("object_type", rec["type"]), rec["type"], 1)
    return dict(scores), signals


# --------------------------------------------------------------------------------------
# Aggregation and decision
# --------------------------------------------------------------------------------------
def aggregate(scores: Dict[str, float], tax: Taxonomy) -> Dict[str, float]:
    """Effective score per node = own + all descendants."""
    eff: Dict[str, float] = defaultdict(float)
    for node, s in scores.items():
        for anc in tax.ancestors(node):
            eff[anc] += s
    return dict(eff)


def decide(eff: Dict[str, float], tax: Taxonomy, cfg: dict, propagated: bool = False) -> dict:
    top_level = [(n, eff.get(n, 0.0)) for n in tax.top_level if n != "UNKNOWN"]
    top_level.sort(key=lambda t: -t[1])
    best, best_s = top_level[0] if top_level else ("UNKNOWN", 0.0)
    second_s = top_level[1][1] if len(top_level) > 1 else 0.0
    margin = best_s - second_s
    share = float(cfg.get("sub_level_share", 0.3))

    def pick_child(parent: str) -> Optional[str]:
        kids = [(c, eff.get(c, 0.0)) for c in tax.children.get(parent, []) if eff.get(c, 0.0) > 0]
        if not kids:
            return None
        kids.sort(key=lambda t: -t[1])
        c, s = kids[0]
        runner = kids[1][1] if len(kids) > 1 else 0.0
        if s >= max(2.0, share * eff.get(parent, 0.0)) and s - runner >= 1.0:
            return c
        return None

    module = best if best_s > 0 else "UNKNOWN"
    submodule = pick_child(module) if module != "UNKNOWN" else None
    area = pick_child(submodule) if submodule else None
    min_score, min_margin = float(cfg.get("auto_min_score", 6.0)), float(cfg.get("auto_min_margin", 3.0))
    if propagated:
        # a helper/Z-table that only inherits its module from its callers needs less own evidence
        min_score = float(cfg.get("propagated_auto_min_score", 3.5))
        min_margin = float(cfg.get("propagated_auto_min_margin", 2.0))
    auto = best_s >= min_score and margin >= min_margin
    if best_s <= 0:
        auto = False
    conf = 0.0
    if best_s > 0:
        conf = min(0.95, 0.45 + 0.03 * best_s + 0.02 * margin)
        if not submodule:
            conf -= 0.08
        if propagated:
            conf -= 0.1
        conf = round(max(0.05, conf), 2)
    ranked = [(n, round(s, 2)) for n, s in top_level[:3] if s > 0]
    return {"module": module, "submodule": submodule, "area": area, "decision": "auto" if auto else "needs_llm",
            "confidence": conf, "top": ranked, "margin": round(margin, 2)}


# --------------------------------------------------------------------------------------
# Dependency graph between custom objects (same system)
# --------------------------------------------------------------------------------------
def build_lookup(inv: List[dict]) -> Dict[str, Dict[str, str]]:
    """per system: NAME -> key for custom objects, plus FM name -> FUGR key."""
    lk: Dict[str, Dict[str, str]] = defaultdict(dict)
    for r in inv:
        lk[r["system"]][r["name"]] = r["key"]
        for c in r.get("children", []):
            lk[r["system"]]["FM:" + c["name"]] = r["key"]
    return lk


def custom_edges(rec: dict, refs: Dict[str, Counter], lk: Dict[str, str]) -> Set[str]:
    out: Set[str] = set()
    me = rec["key"]
    for kind in ("tables", "types", "classes", "includes", "submits", "xml_tokens"):
        for v in refs.get(kind, {}):
            k = lk.get(v)
            if k and k != me:
                out.add(k)
    for v in refs.get("functions", {}):
        k = lk.get("FM:" + v)
        if k and k != me:
            out.add(k)
    return out


def module_vector(scores: Dict[str, float], tax: Taxonomy) -> Dict[str, float]:
    v: Dict[str, float] = defaultdict(float)
    for node, s in scores.items():
        v[tax.module_of(node)] += s
    return dict(v)


# --------------------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ccfg = cfg.classification
    tax = load_taxonomy(cfg.taxonomy_path)
    idx = RuleIndex(tax)
    inv = read_jsonl(cfg.inventory_file)
    roots = {s["id"]: cfg.resolve(s["root"]) for s in cfg.systems}
    lookup = build_lookup(inv)
    log(f"evidence: {len(inv)} objects, {len(tax.rules)} rules")

    results: Dict[str, dict] = {}
    uses: Dict[str, Set[str]] = {}
    for i, rec in enumerate(inv, 1):
        root = roots[rec["system"]]
        refs = refs_from_inventory(rec)
        blob_parts = [rec.get("description", ""), rec.get("package_desc", "")] + rec.get("header_comments", [])
        for c in rec.get("children", []):
            blob_parts.append(c.get("description", ""))
        for relfile in rec.get("source_files", []):
            try:
                text = read_text(root / relfile)
            except OSError as exc:
                log(f"  warn: cannot read {relfile}: {exc}")
                continue
            refs = merge_counters(refs, extract_refs(text))
            blob_parts.extend(list(comment_lines(text))[:40])
        scores, signals = score_object(rec, refs, idx, tax.weights, "\n".join(blob_parts))
        results[rec["key"]] = {"key": rec["key"], "own_scores": scores, "signals": signals,
                               "refs": {k: dict(v.most_common(60)) for k, v in refs.items() if k != "xml_tokens"},
                               "rfc_call": bool(refs.get("flags", {}).get("RFC_CALL"))}
        uses[rec["key"]] = custom_edges(rec, refs, lookup[rec["system"]])
        if i % 500 == 0:
            log(f"  {i}/{len(inv)}")

    users: Dict[str, Set[str]] = defaultdict(set)
    for k, targets in uses.items():
        for t in targets:
            users[t].add(k)

    # propagation
    passes = int(ccfg.get("propagation_passes", 2))
    cap = float(ccfg.get("propagation_cap", 4.0))
    f_users = float(ccfg.get("propagation_factor_users", 1.0))
    f_uses = float(ccfg.get("propagation_factor_uses", 0.6))
    thresh = float(ccfg.get("auto_min_score", 6.0))
    totals: Dict[str, Dict[str, float]] = {k: dict(v["own_scores"]) for k, v in results.items()}
    for _ in range(passes):
        new_totals: Dict[str, Dict[str, float]] = {}
        for k, res in results.items():
            own_mod = module_vector(res["own_scores"], tax)
            if own_mod and max(own_mod.values()) >= thresh:
                new_totals[k] = totals[k]
                continue
            prop: Dict[str, float] = defaultdict(float)
            srcs = []
            for nb, factor in [(n, f_users) for n in users.get(k, ())] + [(n, f_uses) for n in uses.get(k, ())]:
                vec = module_vector(totals.get(nb, {}), tax)
                if not vec:
                    continue
                mx = max(vec.values())
                scale = factor * (min(cap, mx) / mx)
                for mod, s in vec.items():
                    prop[mod] += s * scale
                srcs.append(nb)
            merged = dict(res["own_scores"])
            for mod, s in prop.items():
                merged[mod] = merged.get(mod, 0.0) + s
            new_totals[k] = merged
            res["propagated_from"] = sorted(srcs)[:20]
        totals = new_totals

    out_rows = []
    counts = Counter()
    for rec in inv:
        res = results[rec["key"]]
        eff = aggregate(totals[rec["key"]], tax)
        own_mod = module_vector(res["own_scores"], tax)
        propagated = bool(res.get("propagated_from")) and (not own_mod or max(own_mod.values()) < thresh)
        dec = decide(eff, tax, ccfg, propagated=propagated)
        if propagated and dec["module"] != "UNKNOWN":
            dec["via_propagation"] = True
        counts[dec["decision"]] += 1
        counts["module:" + dec["module"]] += 1
        row = {"key": rec["key"], "decision": dec["decision"], "module": dec["module"], "submodule": dec["submodule"],
               "area": dec["area"], "confidence": dec["confidence"], "top": dec["top"], "margin": dec["margin"],
               "via_propagation": dec.get("via_propagation", False),
               "propagated_from": res.get("propagated_from", []),
               "signals": sorted(res["signals"], key=lambda s: -s["weight"])[:40],
               "refs": res["refs"], "rfc_call": res["rfc_call"],
               "uses": sorted(uses.get(rec["key"], ()))[:50], "used_by": sorted(users.get(rec["key"], ()))[:50]}
        out_rows.append(row)
    n = write_jsonl(cfg.evidence_file, out_rows)
    log(f"wrote {n} -> {cfg.evidence_file}; auto={counts['auto']} needs_llm={counts['needs_llm']}")
    mods = ", ".join(f"{k[7:]}={v}" for k, v in counts.most_common() if k.startswith("module:"))
    print(f"EVIDENCE_OK objects={n} auto={counts['auto']} needs_llm={counts['needs_llm']} modules: {mods}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
