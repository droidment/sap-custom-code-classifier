"""Stage 1: walk the abapGit export roots and build work/inventory.jsonl.

One record per repository object (CLAS, PROG, FUGR, TABL, ...). Function modules are recorded
as children of their function group. Nothing under the roots is ever modified.

Usage:  py tools/inventory.py --config migration.config.json
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    base_argparser, code_lines, comment_lines, load_config, log, make_key, normalize_source,
    parse_abapgit_filename, read_text, source_hash, write_jsonl,
)

SOURCE_EXT = {".abap", ".asddls", ".asdcls", ".asbdef", ".js", ".xslt"}

# Tags whose text is a human description, in priority order per object type.
DESC_TAGS = {
    "CLAS": ["DESCRIPT"], "INTF": ["DESCRIPT"], "PROG": [], "FUGR": ["AREAT"],
    "TABL": ["DDTEXT"], "DTEL": ["DDTEXT"], "DOMA": ["DDTEXT"], "TTYP": ["DDTEXT"], "VIEW": ["DDTEXT"],
    "SHLP": ["DDTEXT"], "MSAG": ["STEXT"], "TRAN": ["TTEXT"], "DEVC": ["CTEXT"], "ENHO": ["SHORTTEXT"],
    "ENHS": ["SHORTTEXT"], "SXCI": ["TEXT"], "DDLS": ["DDTEXT"], "DDLX": ["DDTEXT"], "DCLS": ["DDTEXT"],
    "SSFO": ["CAPTION", "TDDESC", "DESCRIPT"], "SFPF": ["TEXT", "DESCRIPT"], "SFPI": ["TEXT", "DESCRIPT"],
    "WDYN": ["DESCRIPT"], "SMIM": ["DESCRIPT"], "PARA": ["PARTEXT"], "TOBJ": ["DDTEXT"], "SUSO": ["TTEXT"],
    "AUTH": ["TTEXT"], "ENQU": ["DDTEXT"], "SRVD": ["DDTEXT"], "SRVB": ["DESCRIPTION"], "BDEF": ["DDTEXT"],
    "IWPR": ["DESCRIPTION"], "IWSV": ["DESCRIPTION"], "IWMO": ["DESCRIPTION"], "IWOM": ["DESCRIPTION"],
    "W3MI": ["TEXT"], "W3HT": ["TEXT"], "SICF": ["DESCRIPTION"], "XSLT": ["DESCRIPT"], "TYPE": ["DDTEXT"],
    "CMOD": ["MODTEXT"], "SMOD": ["MODTEXT"], "FORM": ["TDTITLE"], "STYL": ["TDTEXT"], "CHAR": ["DDTEXT"],
}
GENERIC_DESC_TAGS = ["DESCRIPT", "DDTEXT", "CTEXT", "STEXT", "TTEXT", "SHORTTEXT", "AREAT", "TEXT",
                     "DESCRIPTION", "CAPTION", "MODTEXT", "TDTITLE"]

# Reference-bearing tags in object xml (standard object names the object is tied to).
REF_TAGS = ["SPOT_NAME", "BADI_DEF", "EXIT_NAME", "ORIGINAL_OBJECT", "PROGRAM", "PGMNA", "CLSNAME",
            "IMPL_CLASS", "ROLLNAME", "DOMNAME", "CHECKTABLE", "SELMETHOD", "TABNAME", "ROWTYPE",
            "LDBNAME", "SUPERCLASS", "REFCLSNAME", "ENHNAME", "INTERFACE", "FUNCNAME", "INCLUDE",
            "TRANSACTION", "TCODE", "FORMNAME", "ENHSPOTCOMPOSITE", "OBJ_NAME", "OBJ_TYPE", "FUNC"]


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def _findall_text(root: ET.Element, tag: str) -> List[str]:
    return [t for t in (_text(e) for e in root.iter(tag)) if t]


def _parse_xml(path: Path) -> Optional[ET.Element]:
    try:
        return ET.fromstring(read_text(path))
    except ET.ParseError as exc:
        log(f"  warn: cannot parse xml {path}: {exc}")
        return None


def _uppercase_tokens(text: str) -> List[str]:
    """Candidate SAP object names inside non-ABAP files (smartforms, adobe forms, cds, ...)."""
    return sorted(set(re.findall(r"\b[A-Z][A-Z0-9_/]{3,40}\b", text)))


def extract_xml_meta(obj_type: str, root: ET.Element) -> dict:
    meta: dict = {"description": "", "refs": {}, "children": [], "extra": {}}
    # Description
    for tag in DESC_TAGS.get(obj_type, []) + GENERIC_DESC_TAGS:
        found = _findall_text(root, tag)
        if found:
            meta["description"] = found[0]
            break
    if obj_type == "PROG":
        # report title lives in TPOOL item with ID 'R'
        for item in root.iter("item"):
            if _text(item.find("ID")) == "R":
                meta["description"] = _text(item.find("ENTRY"))
                break
        progdir = next(root.iter("PROGDIR"), None)
        if progdir is not None:
            meta["extra"]["ldb"] = _text(progdir.find("LDBNAME"))
            meta["extra"]["subc"] = _text(progdir.find("SUBC"))
    if obj_type == "FUGR":
        for item in root.iter("item"):
            fn = _text(item.find("FUNCNAME"))
            if fn:
                meta["children"].append({"type": "FUNC", "name": fn.upper(), "description": _text(item.find("SHORT_TEXT")),
                                         "remote": _text(item.find("REMOTE_CALL")) in ("R", "X")})
        meta["extra"]["includes"] = _findall_text(root, "INCLUDES") or [_text(i) for i in root.iter("SOBJ_NAME")]
    if obj_type == "TABL":
        fields = []
        for fld in root.iter("DD03P"):
            fields.append({"field": _text(fld.find("FIELDNAME")), "rollname": _text(fld.find("ROLLNAME")),
                           "checktable": _text(fld.find("CHECKTABLE")), "precfield": _text(fld.find("PRECFIELD"))})
        meta["extra"]["fields"] = fields[:200]
        dd02 = next(root.iter("DD02V"), None)
        if dd02 is not None:
            meta["extra"]["tabclass"] = _text(dd02.find("TABCLASS"))
    if obj_type == "TRAN":
        tstc = next(root.iter("TSTC"), None)
        if tstc is not None:
            meta["extra"]["program"] = _text(tstc.find("PGMNA"))
            meta["extra"]["screen"] = _text(tstc.find("DYPNO"))
    if obj_type == "CLAS":
        vseo = next(root.iter("VSEOCLASS"), None)
        if vseo is not None:
            meta["extra"]["category"] = _text(vseo.find("CATEGORY"))
    refs: Dict[str, List[str]] = defaultdict(list)
    for tag in REF_TAGS:
        for v in _findall_text(root, tag):
            if v and v.upper() not in refs[tag]:
                refs[tag].append(v.upper())
    meta["refs"] = dict(refs)
    if obj_type in ("SSFO", "SFPF", "SFPI", "DDLS", "DCLS", "WDYN", "W3MI", "IWPR", "SRVD", "SRVB", "ENHO", "SXCI", "VIEW"):
        meta["extra"]["xml_tokens"] = _uppercase_tokens(ET.tostring(root, encoding="unicode"))[:400]
    return meta


def read_folder_logic(root: Path) -> str:
    """abapGit .abapgit.xml FOLDER_LOGIC (PREFIX|FULL|MIXED). Default FULL (folder name = package)."""
    for cand in (root / ".abapgit.xml", root.parent / ".abapgit.xml"):
        if cand.exists():
            x = _parse_xml(cand)
            if x is not None:
                v = _findall_text(x, "FOLDER_LOGIC")
                if v:
                    return v[0].upper()
    return "FULL"


def package_name_for(folder_rel: Path, logic: str, chain_names: List[str]) -> str:
    if str(folder_rel) in ("", "."):
        return "$ROOT"
    if logic == "PREFIX":
        return "_".join(n.upper() for n in chain_names)
    return folder_rel.name.upper()


def walk_system(system: dict, root: Path) -> Tuple[List[dict], Counter]:
    sysid = system["id"]
    logic = read_folder_logic(root)
    log(f"[{sysid}] root={root} folder_logic={logic}")
    records: Dict[str, dict] = {}
    warnings: Counter = Counter()
    package_desc: Dict[str, str] = {}

    all_files = [p for p in root.rglob("*") if p.is_file()]
    # pass 1: packages
    for p in all_files:
        if p.name.lower() == "package.devc.xml":
            x = _parse_xml(p)
            if x is not None:
                package_desc[str(p.parent)] = extract_xml_meta("DEVC", x)["description"]

    for p in sorted(all_files):
        parsed = parse_abapgit_filename(p.name)
        if not parsed:
            if p.suffix.lower() in SOURCE_EXT or p.suffix.lower() == ".xml":
                warnings["unparsed_filename"] += 1
            continue
        name, obj_type, rest = parsed
        if obj_type == "DEVC":
            continue
        folder_rel = p.parent.relative_to(root)
        chain = [part for part in folder_rel.parts]
        package = package_name_for(folder_rel, logic, chain)
        key = make_key(sysid, obj_type, name)
        rec = records.get(key)
        if rec is None:
            rec = {
                "key": key, "system": sysid, "company": system.get("company", ""), "type": obj_type, "name": name,
                "package": package, "package_path": str(folder_rel).replace("\\", "/"),
                "package_desc": package_desc.get(str(p.parent), ""),
                "description": "", "files": [], "source_files": [], "xml_file": None,
                "children": [], "refs": {}, "extra": {}, "loc": 0, "source_hash": None,
                "header_comments": [], "fm_sources": {},
            }
            records[key] = rec
        relfile = str(p.relative_to(root)).replace("\\", "/")
        rec["files"].append(relfile)
        if p.suffix.lower() == ".xml" and rest.lower() == "xml":
            rec["xml_file"] = relfile
            x = _parse_xml(p)
            if x is not None:
                meta = extract_xml_meta(obj_type, x)
                rec["description"] = meta["description"] or rec["description"]
                rec["children"] = meta["children"] or rec["children"]
                rec["refs"] = meta["refs"]
                rec["extra"].update(meta["extra"])
        elif p.suffix.lower() in SOURCE_EXT:
            rec["source_files"].append(relfile)

    # pass 2: source metrics, FM source mapping, header comments
    for rec in records.values():
        normalized_parts = []
        loc = 0
        headers: List[str] = []
        fm_names = {c["name"] for c in rec["children"]}
        for relfile in rec["source_files"]:
            text = read_text(root / relfile)
            loc += sum(1 for _ in code_lines(text))
            normalized_parts.append(normalize_source(text))
            if len(headers) < 12:
                for c in comment_lines(text):
                    headers.append(c[:160])
                    if len(headers) >= 12:
                        break
            if rec["type"] == "FUGR":
                parsed = parse_abapgit_filename(Path(relfile).name)
                if parsed:
                    sub = parsed[2].rsplit(".", 1)[0].upper()
                    if sub in fm_names:
                        rec["fm_sources"][sub] = relfile
        rec["loc"] = loc
        rec["header_comments"] = headers
        rec["source_hash"] = source_hash("\n".join(normalized_parts)) if normalized_parts else None
        if rec["type"] == "FUGR" and not rec["children"]:
            warnings["fugr_without_function_list"] += 1
    return list(records.values()), warnings


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    all_records: List[dict] = []
    totals: Counter = Counter()
    for system in cfg.systems:
        root = cfg.resolve(system["root"])
        if not root.exists():
            log(f"[{system['id']}] ERROR root does not exist: {root}")
            return 2
        recs, warnings = walk_system(system, root)
        all_records.extend(recs)
        by_type = Counter(r["type"] for r in recs)
        log(f"[{system['id']}] {len(recs)} objects, {len({r['package'] for r in recs})} packages, "
            f"{sum(len(r['children']) for r in recs)} function modules; types: "
            + ", ".join(f"{t}={n}" for t, n in by_type.most_common()))
        for w, n in warnings.items():
            log(f"[{system['id']}] warn {w}: {n}")
        totals.update(by_type)
    n = write_jsonl(cfg.inventory_file, all_records)
    log(f"wrote {n} records -> {cfg.inventory_file}")
    print(f"INVENTORY_OK objects={n} systems={len(cfg.systems)} file={cfg.inventory_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
