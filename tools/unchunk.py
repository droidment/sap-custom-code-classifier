"""Stage 0 (chunked exports only): rebuild an abapGit-style folder from chained .abapchunk files.

Input  <root>/<PACKAGE>/<prefix>_<NNNN>.abapchunk   (plain text, size-based chunks, objects separated by
       marker lines; no metadata)
Output work/unchunked/<SYS>/<package>/<name>.<type>.abap|xml, package.devc.xml, _manifest.jsonl
       work/unchunk_unresolved.json + work/unchunk_unresolved/<SYS>/<pkg>/<seq>.txt for segments the
       parser could not attribute (the abap-splitter subagent names them; --apply-resolution applies that)

Usage
  py tools/unchunk.py --config migration.config.json                 rebuild changed packages
  py tools/unchunk.py --config migration.config.json --inspect [SYS] [PKG]
  py tools/unchunk.py --config migration.config.json --apply-resolution
  py tools/unchunk.py --config migration.config.json --force         rebuild everything
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config, log, read_json, read_jsonl, read_text, write_json, write_jsonl  # noqa: E402

CHUNK_RE = re.compile(r"^(?P<prefix>.+?)_(?P<num>\d+)\.[^.]+$", re.IGNORECASE)

# Built-in marker candidates, tried in order; the first with >= 2 hits in the sample wins.
# Each has a named group 'name' and optionally 'type'.
BUILTIN_MARKERS: List[Tuple[str, str]] = [
    # type and name are optional so that a marker without them still starts a segment (-> unresolved)
    # '###OBJECT   D66:FUNC:Y2F_NAME   FUNC   Y2F_NAME' (SAP-side export with ###END_OBJECT / * ###END_PROGRAM lines)
    ("hash_object", r"^#{2,}\s*OBJECT\b(?:[\s:]*(?:[A-Z0-9_]+:)?(?P<type>[A-Z]{4})\b[:\s]*(?P<name>/?[A-Z][A-Z0-9_/]+)?)?"),
    ("object_comment", r"^\*{2,}\s*(?:OBJECT|OBJ|BEGIN)(?:\s+OF)?\b[:\s]*(?P<type>[A-Z]{4}\b)?[:\s]*(?P<name>/?[A-Z][A-Z0-9_/]+)?"),
    ("hash_comment", r"^[\*\"]\s*#{2,}\s*(?!END_)(?P<type>[A-Z]{4}\b)?\s*(?P<name>/?[A-Z][A-Z0-9_/]+)?"),
    ("header_box", r"^\*&\s*(?:Report|Include|Program|Modulpool|Module pool)\s+(?P<name>/?[A-Z0-9_/]+)"),
    ("statement", r"^(?:REPORT|PROGRAM|FUNCTION-POOL)\s+(?P<name>/?[A-Z0-9_/]+)\b|^CLASS\s+(?P<name2>/?[A-Z0-9_/]+)\s+DEFINITION\b(?!.*\b(?:LOCAL|DEFERRED|LOAD)\b)|^INTERFACE\s+(?P<name3>/?[A-Z0-9_/]+)\s+PUBLIC\b"),
]
TYPE_START = {
    "REPORT": "PROG", "PROGRAM": "PROG", "FUNCTION-POOL": "FUGR", "CLASS": "CLAS", "INTERFACE": "INTF", "FUNCTION": "FUNC",
}
RX_REPORT = re.compile(r"^(REPORT|PROGRAM)\s+(/?[A-Z0-9_/]+)", re.I)
RX_POOL = re.compile(r"^FUNCTION-POOL\s+(/?[A-Z0-9_/]+)", re.I)
RX_CLASS_DEF = re.compile(r"^CLASS\s+(/?[A-Z0-9_/]+)\s+DEFINITION\b(.*)$", re.I)
RX_CLASS_IMP = re.compile(r"^CLASS\s+(/?[A-Z0-9_/]+)\s+IMPLEMENTATION\b", re.I)
RX_INTF = re.compile(r"^INTERFACE\s+(/?[A-Z0-9_/]+)\s+PUBLIC\b", re.I)
RX_FUNC = re.compile(r"^FUNCTION\s+(/?[A-Z0-9_/]+)\s*\.", re.I)
RX_ENDFUNC = re.compile(r"^ENDFUNCTION\s*\.", re.I)
RX_INCLUDE_BOX = re.compile(r"^\*&\s*Include\s+(/?[A-Z0-9_/]+)", re.I)
RX_END_OBJECT = re.compile(r"^#{2,}\s*END_OBJECT\b", re.I)                       # not ABAP: dropped from the object text
RX_END_PROGRAM = re.compile(r"^[\*\"]?\s*#{2,}\s*END_PROGRAM\s+(/?[A-Z0-9_/]+)", re.I)  # main program of the object
RX_SAPL = re.compile(r"^(/[A-Z0-9_]+/)?SAPL([A-Z0-9_]+)$", re.I)
DECOR = re.compile(r"^[\*&\-=_ \t]*$")


# --------------------------------------------------------------------------------------
@dataclass
class Segment:
    seq: int
    marker: str                 # the marker line that opened it ('' if none)
    mtype: Optional[str]        # type from the marker, if any
    mname: Optional[str]        # name from the marker, if any
    lines: List[str] = field(default_factory=list)
    start_line: int = 0


@dataclass
class ObjectOut:
    otype: str
    name: str
    lines: List[str]
    description: str = ""
    fms: List[Tuple[str, str, List[str]]] = field(default_factory=list)   # (fm name, short text, lines)
    flags: List[str] = field(default_factory=list)
    source: str = "parser"
    seg_range: Tuple[int, int] = (0, 0)


def chunk_files(folder: Path, glob: str) -> Tuple[List[Path], List[str]]:
    """Chunk files of one package in chain order, plus warnings (gaps, mixed prefixes)."""
    groups: Dict[str, List[Tuple[int, Path]]] = defaultdict(list)
    for p in folder.glob(glob):
        if not p.is_file():
            continue
        m = CHUNK_RE.match(p.name)
        if m:
            groups[m.group("prefix").lower()].append((int(m.group("num")), p))
        else:
            groups[p.stem.lower()].append((0, p))
    ordered: List[Path] = []
    warnings: List[str] = []
    for prefix in sorted(groups):
        items = sorted(groups[prefix])
        nums = [n for n, _ in items]
        for a, b in zip(nums, nums[1:]):
            if b != a + 1:
                warnings.append(f"{folder.name}/{prefix}: gap between chunk {a} and {b}")
        ordered.extend(p for _, p in items)
    if len(groups) > 1:
        warnings.append(f"{folder.name}: {len(groups)} chunk chains ({', '.join(sorted(groups))}) concatenated in name order")
    return ordered, warnings


def concatenate(files: Iterable[Path]) -> str:
    """Raw concatenation: size-based chunks end mid-line, so no separator may be inserted."""
    return "".join(read_text(p) for p in files)


def detect_marker(sample: str, configured: Optional[str]) -> Optional[Tuple[str, re.Pattern]]:
    if configured:
        return "config", re.compile(configured, re.I | re.M)
    for minimum in (2, 1):        # prefer a pattern that repeats; a one-object package still gets its marker
        for name, pat in BUILTIN_MARKERS:
            rx = re.compile(pat, re.I | re.M)
            if len(rx.findall(sample)) >= minimum:
                return name, rx
    return None


def _marker_fields(m: re.Match) -> Tuple[Optional[str], Optional[str]]:
    gd = m.groupdict()
    name = gd.get("name") or gd.get("name2") or gd.get("name3")
    mtype = gd.get("type")
    return (mtype.upper() if mtype else None), (name.upper() if name else None)


def split_segments(text: str, rx: Optional[re.Pattern]) -> List[Segment]:
    segs: List[Segment] = []
    cur = Segment(seq=0, marker="", mtype=None, mname=None, start_line=1)
    for no, line in enumerate(text.splitlines(), start=1):
        m = rx.match(line) if rx else None
        if m:
            if cur.lines and not all(DECOR.match(l) for l in cur.lines):
                segs.append(cur)
            mtype, mname = _marker_fields(m)
            cur = Segment(seq=len(segs) + 1, marker=line.strip(), mtype=mtype, mname=mname, start_line=no)
            # statement-style markers are part of the object; comment- and ###-style markers are not
            if not line.lstrip().startswith(("*", '"', "#")):
                cur.lines.append(line)
            continue
        if RX_END_OBJECT.match(line):
            continue
        cur.lines.append(line)
    if cur.lines and not all(DECOR.match(l) for l in cur.lines):
        segs.append(cur)
    return segs


def first_description(lines: List[str]) -> str:
    for l in lines[:40]:
        s = l.strip()
        if s.startswith("*") or s.startswith('"'):
            body = s.lstrip("*&\"").strip()
            if body and not DECOR.match(body) and not re.match(r"^(Report|Include|Program)\s+\S+$", body, re.I) \
                    and not re.match(r"^(OBJECT|OBJ|BEGIN)\b", body, re.I) and "---" not in body:
                return body[:120]
    return ""


def infer_type(seg: Segment) -> Tuple[Optional[str], Optional[str], List[str]]:
    """(type, name, flags) from the segment's own statements; None if undecidable."""
    flags: List[str] = []
    for l in seg.lines[:200]:
        s = l.strip()
        if not s or s.startswith(("*", '"')):
            continue
        if m := RX_REPORT.match(s):
            return "PROG", m.group(2).upper(), flags
        if m := RX_POOL.match(s):
            return "FUGR", m.group(1).upper(), flags
        if m := RX_CLASS_DEF.match(s):
            rest = m.group(2).upper()
            if "LOCAL" in rest or "DEFERRED" in rest or "LOAD" in rest or m.group(1).upper().startswith(("LCL_", "LTCL_", "LTC_")):
                continue
            return "CLAS", m.group(1).upper(), flags
        if m := RX_CLASS_IMP.match(s):
            if not m.group(1).upper().startswith(("LCL_", "LTCL_", "LTC_")):
                return "CLAS", m.group(1).upper(), ["implementation_only"]
        if m := RX_INTF.match(s):
            return "INTF", m.group(1).upper(), flags
        if m := RX_FUNC.match(s):
            return "FUNC", m.group(1).upper(), flags
        break
    for l in seg.lines[:20]:
        if m := RX_INCLUDE_BOX.match(l.strip()):
            return "PROG", m.group(1).upper(), ["include"]
    return None, None, flags


def fugr_from_end_program(lines: List[str]) -> Optional[str]:
    """'* ###END_PROGRAM SAPLZFG' inside a function module segment names its function group ZFG."""
    for l in reversed(lines[-50:]):
        m = RX_END_PROGRAM.match(l.strip())
        if m:
            sm = RX_SAPL.match(m.group(1).upper())
            return (sm.group(1) or "") + sm.group(2) if sm else None
    return None


def synthetic_fugr_name(fm: str) -> str:
    parts = fm.split("_")
    if len(parts) >= 3:
        return (parts[0] + parts[1] + "_" + parts[2])[:30] if parts[0] in ("Z", "Y") else "_".join(parts[:2])[:30]
    return (fm + "_FG")[:30]


def assemble(segments: List[Segment], pkg: str) -> Tuple[List[ObjectOut], List[Segment]]:
    """Turn segments into objects; function modules attach to the current function group."""
    objs: Dict[Tuple[str, str], ObjectOut] = {}
    order: List[Tuple[str, str]] = []
    unresolved: List[Segment] = []
    current_fugr: Optional[str] = None

    def get(otype: str, name: str) -> ObjectOut:
        k = (otype, name)
        if k not in objs:
            objs[k] = ObjectOut(otype=otype, name=name, lines=[])
            order.append(k)
        return objs[k]

    for seg in segments:
        itype, iname, iflags = infer_type(seg)
        otype = seg.mtype or itype
        name = seg.mname or iname
        if otype == "FUNC" and seg.mtype is None:
            # FUNCTION blocks: split on ENDFUNCTION; the first FUNCTION name may differ from iname when
            # a marker named the group explicitly
            pass
        if not otype or not name:
            unresolved.append(seg)
            continue
        otype = otype.upper()
        if otype == "FUNC":
            fm_name = iname or name
            hinted = fugr_from_end_program(seg.lines)
            fg = hinted or current_fugr or synthetic_fugr_name(fm_name)
            o = get("FUGR", fg)
            if hinted:
                if "fugr_from_end_marker" not in o.flags:
                    o.flags.append("fugr_from_end_marker")
            elif not current_fugr and "synthetic_fugr" not in o.flags:
                o.flags.append("synthetic_fugr")
            o.fms.append((fm_name, first_description(seg.lines), seg.lines))
            o.seg_range = (o.seg_range[0] or seg.seq, seg.seq)
            continue
        if otype == "FUGR":
            current_fugr = name
        elif otype in ("PROG", "CLAS", "INTF"):
            pass
        else:
            # unknown 4-letter type from a marker (TABL, DTEL, ...): keep as generic text object
            otype = otype[:4]
        o = get(otype, name)
        if o.lines:
            o.lines.append("")
        o.lines.extend(seg.lines)
        o.flags.extend(f for f in iflags if f not in o.flags)
        if not o.description:
            o.description = first_description(seg.lines)
        o.seg_range = (o.seg_range[0] or seg.seq, seg.seq)
        # a FUGR segment may itself contain FUNCTION ... ENDFUNCTION blocks: split them out
        if otype == "FUGR":
            o.lines, extra = split_function_blocks(o.lines)
            for fm_name, fm_lines in extra:
                o.fms.append((fm_name, first_description(fm_lines), fm_lines))
    return [objs[k] for k in order], unresolved


def split_function_blocks(lines: List[str]) -> Tuple[List[str], List[Tuple[str, List[str]]]]:
    top: List[str] = []
    fms: List[Tuple[str, List[str]]] = []
    cur: Optional[Tuple[str, List[str]]] = None
    for l in lines:
        s = l.strip()
        if cur is None:
            if m := RX_FUNC.match(s):
                cur = (m.group(1).upper(), [l])
            else:
                top.append(l)
        else:
            cur[1].append(l)
            if RX_ENDFUNC.match(s):
                fms.append(cur)
                cur = None
    if cur:
        fms.append(cur)
    return top, fms


# --------------------------------------------------------------------------------------
def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(serializer: str, inner: str) -> str:
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<abapGit version="v1.0.0" serializer="{serializer}" serializer_version="v1.0.0">\n'
            f' <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">\n  <asx:values>{inner}</asx:values>\n </asx:abap>\n</abapGit>\n')


def write_object(out_pkg: Path, o: ObjectOut) -> List[str]:
    fn = o.name.lower().replace("/", "#")
    files: List[str] = []
    desc = xml_escape(o.description)
    src = "\n".join(o.lines).rstrip() + "\n"
    if o.otype == "PROG":
        (out_pkg / f"{fn}.prog.abap").write_text(src, encoding="utf-8")
        (out_pkg / f"{fn}.prog.xml").write_text(wrap("LCL_OBJECT_PROG",
            f"<PROGDIR><NAME>{xml_escape(o.name)}</NAME><SUBC>{'I' if 'include' in o.flags else '1'}</SUBC></PROGDIR>"
            f"<TPOOL><item><ID>R</ID><ENTRY>{desc}</ENTRY><LENGTH>{len(o.description)}</LENGTH></item></TPOOL>"), encoding="utf-8")
        files += [f"{fn}.prog.abap", f"{fn}.prog.xml"]
    elif o.otype == "CLAS":
        (out_pkg / f"{fn}.clas.abap").write_text(src, encoding="utf-8")
        (out_pkg / f"{fn}.clas.xml").write_text(wrap("LCL_OBJECT_CLAS",
            f"<VSEOCLASS><CLSNAME>{xml_escape(o.name)}</CLSNAME><LANGU>E</LANGU><DESCRIPT>{desc}</DESCRIPT><STATE>1</STATE></VSEOCLASS>"), encoding="utf-8")
        files += [f"{fn}.clas.abap", f"{fn}.clas.xml"]
    elif o.otype == "INTF":
        (out_pkg / f"{fn}.intf.abap").write_text(src, encoding="utf-8")
        (out_pkg / f"{fn}.intf.xml").write_text(wrap("LCL_OBJECT_INTF",
            f"<VSEOINTERF><CLSNAME>{xml_escape(o.name)}</CLSNAME><LANGU>E</LANGU><DESCRIPT>{desc}</DESCRIPT></VSEOINTERF>"), encoding="utf-8")
        files += [f"{fn}.intf.abap", f"{fn}.intf.xml"]
    elif o.otype == "FUGR":
        items = "".join(f"<item><FUNCNAME>{xml_escape(n)}</FUNCNAME><SHORT_TEXT>{xml_escape(t)}</SHORT_TEXT></item>" for n, t, _ in o.fms)
        (out_pkg / f"{fn}.fugr.xml").write_text(wrap("LCL_OBJECT_FUGR",
            f"<AREAT>{desc}</AREAT><INCLUDES><SOBJ_NAME>L{xml_escape(o.name)}TOP</SOBJ_NAME></INCLUDES><FUNCTIONS>{items}</FUNCTIONS>"), encoding="utf-8")
        top = src if o.lines else f"FUNCTION-POOL {o.name.lower()}.\n"
        (out_pkg / f"{fn}.fugr.l{fn}top.abap").write_text(top, encoding="utf-8")
        files += [f"{fn}.fugr.xml", f"{fn}.fugr.l{fn}top.abap"]
        for n, _, lines in o.fms:
            fmf = f"{fn}.fugr.{n.lower().replace('/', '#')}.abap"
            (out_pkg / fmf).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            files.append(fmf)
    else:
        ext = o.otype.lower()
        (out_pkg / f"{fn}.{ext}.abap").write_text(src, encoding="utf-8")
        (out_pkg / f"{fn}.{ext}.xml").write_text(wrap(f"LCL_OBJECT_{o.otype}", f"<DESCRIPT>{desc}</DESCRIPT>"), encoding="utf-8")
        files += [f"{fn}.{ext}.abap", f"{fn}.{ext}.xml"]
    return files


def package_signature(files: List[Path]) -> str:
    h = hashlib.sha1()
    for p in files:
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{int(st.st_mtime)};".encode())
    return h.hexdigest()


def process_package(system: dict, pkg_dir: Path, out_dir: Path, glob: str, configured_marker: Optional[str],
                    stats: Counter, unresolved_out: List[dict], formats: Dict[str, dict], force: bool,
                    manifest_rows: List[dict], old_sig: Dict[str, str], unchanged: set) -> None:
    files, warns = chunk_files(pkg_dir, glob)
    for w in warns:
        log(f"  warn: {w}")
    if not files:
        return
    pkg = pkg_dir.name.upper()
    sig = package_signature(files)
    out_pkg = out_dir / pkg_dir.name.lower()
    if not force and old_sig.get(pkg) == sig and out_pkg.exists():
        stats["packages_unchanged"] += 1
        if (out_dir / "_manifest.jsonl").exists():
            manifest_rows.extend(r for r in read_jsonl(out_dir / "_manifest.jsonl") if r["package"] == pkg)
        unchanged.add(f"{system['id']}|{pkg}")
        return
    text = concatenate(files)
    det = detect_marker(text[:200000], configured_marker)
    rx = det[1] if det else None
    formats[f"{system['id']}|{pkg}"] = {"marker": det[0] if det else None, "pattern": rx.pattern if rx else None,
                                        "chunks": len(files), "chars": len(text)}
    segments = split_segments(text, rx)
    objects, unresolved = assemble(segments, pkg)
    if out_pkg.exists():
        for p in out_pkg.iterdir():
            p.unlink()
    out_pkg.mkdir(parents=True, exist_ok=True)
    (out_pkg / "package.devc.xml").write_text(wrap("LCL_OBJECT_DEVC", f"<DEVC><CTEXT>{xml_escape(pkg)} (from chunks)</CTEXT></DEVC>"), encoding="utf-8")
    for o in objects:
        written = write_object(out_pkg, o)
        manifest_rows.append({"system": system["id"], "package": pkg, "type": o.otype, "name": o.name, "description": o.description,
                              "fms": [n for n, _, _ in o.fms], "lines": len(o.lines) + sum(len(l) for _, _, l in o.fms),
                              "segments": list(o.seg_range), "flags": o.flags, "source": o.source, "files": written, "sig": sig})
        stats["objects"] += 1
        stats["fms"] += len(o.fms)
    for seg in unresolved:
        seq_id = f"{system['id']}|{pkg}|{seg.seq:05d}"
        udir = out_dir.parent.parent / "unchunk_unresolved" / system["id"] / pkg_dir.name.lower()
        udir.mkdir(parents=True, exist_ok=True)
        (udir / f"{seg.seq:05d}.txt").write_text("\n".join(seg.lines) + "\n", encoding="utf-8")
        unresolved_out.append({"id": seq_id, "system": system["id"], "package": pkg, "seq": seg.seq, "marker": seg.marker,
                               "start_line": seg.start_line, "lines": len(seg.lines),
                               "file": str(udir / f"{seg.seq:05d}.txt"), "head": seg.lines[:60]})
        stats["unresolved"] += 1
    stats["packages"] += 1


def apply_resolution(cfg, systems: List[dict]) -> Counter:
    """Apply work/unchunk_resolution.json written by the abap-splitter subagent."""
    stats = Counter()
    res_file = cfg.work_dir / "unchunk_resolution.json"
    unres_file = cfg.work_dir / "unchunk_unresolved.json"
    if not res_file.exists() or not unres_file.exists():
        log("nothing to apply: missing unchunk_resolution.json or unchunk_unresolved.json")
        return stats
    res = read_json(res_file)
    res = res.get("results", res) if isinstance(res, dict) else res
    unres = {u["id"]: u for u in read_json(unres_file).get("segments", [])}
    by_sys = {s["id"]: s for s in systems}
    remaining = dict(unres)
    for r in res:
        sid = r.get("segment")
        u = unres.get(sid)
        if not u:
            log(f"  warn: resolution for unknown segment {sid}")
            stats["invalid"] += 1
            continue
        rtype = str(r.get("type", "")).upper()
        name = str(r.get("name", "")).upper()
        if rtype == "SKIP":
            remaining.pop(sid, None)
            stats["skipped"] += 1
            continue
        if rtype not in ("PROG", "CLAS", "INTF", "FUGR", "FUNC") or not name:
            log(f"  warn: invalid resolution for {sid}: type={rtype} name={name}")
            stats["invalid"] += 1
            continue
        lines = read_text(Path(u["file"])).splitlines()
        out_pkg = cfg.unchunked_dir(by_sys[u["system"]]) / u["package"].lower()
        out_pkg.mkdir(parents=True, exist_ok=True)
        if rtype == "FUNC":
            fg = str(r.get("parent_fugr") or synthetic_fugr_name(name)).upper()
            o = ObjectOut(otype="FUGR", name=fg, lines=[], fms=[(name, first_description(lines), lines)], source="llm")
            existing = out_pkg / f"{fg.lower()}.fugr.xml"
            if existing.exists():
                # append FM to existing group: rewrite xml with the extra function
                xml = existing.read_text(encoding="utf-8")
                item = f"<item><FUNCNAME>{xml_escape(name)}</FUNCNAME><SHORT_TEXT>{xml_escape(first_description(lines))}</SHORT_TEXT></item>"
                existing.write_text(xml.replace("</FUNCTIONS>", item + "</FUNCTIONS>"), encoding="utf-8")
                (out_pkg / f"{fg.lower()}.fugr.{name.lower()}.abap").write_text("\n".join(lines) + "\n", encoding="utf-8")
                files = [f"{fg.lower()}.fugr.{name.lower()}.abap"]
            else:
                files = write_object(out_pkg, o)
        else:
            o = ObjectOut(otype=rtype, name=name, lines=lines, description=first_description(lines), source="llm")
            files = write_object(out_pkg, o)
        manifest = cfg.unchunked_dir(by_sys[u["system"]]) / "_manifest.jsonl"
        rows = read_jsonl(manifest) if manifest.exists() else []
        rows.append({"system": u["system"], "package": u["package"], "type": o.otype, "name": o.name, "description": o.description,
                     "fms": [n for n, _, _ in o.fms], "lines": len(lines), "segments": [u["seq"], u["seq"]], "flags": ["llm_resolved"],
                     "source": "llm", "files": files, "sig": "llm"})
        write_jsonl(manifest, rows)
        remaining.pop(sid, None)
        stats["applied"] += 1
    write_json(unres_file, {"segments": list(remaining.values())})
    return stats


def inspect(cfg, systems: List[dict], sys_filter: Optional[str], pkg_filter: Optional[str]) -> None:
    for system in systems:
        if sys_filter and system["id"] != sys_filter:
            continue
        root = cfg.resolve(system["root"])
        glob = system.get("chunk_glob", "*.abapchunk")
        pkgs = [p for p in sorted(root.iterdir()) if p.is_dir()] if root.exists() else []
        print(f"== {system['id']} root={root} packages={len(pkgs)} glob={glob}")
        for pkg_dir in pkgs:
            if pkg_filter and pkg_dir.name.upper() != pkg_filter.upper():
                continue
            files, warns = chunk_files(pkg_dir, glob)
            print(f"-- {pkg_dir.name}: {len(files)} chunk files" + (f" ({files[0].name} .. {files[-1].name})" if files else ""))
            for w in warns:
                print(f"   warn: {w}")
            if not files:
                continue
            text = concatenate(files[:3])
            det = detect_marker(text, system.get("object_marker"))
            print(f"   marker: {det[0] if det else 'NONE DETECTED'}  pattern: {det[1].pattern if det else '-'}")
            if det:
                n = 0
                for no, line in enumerate(text.splitlines(), start=1):
                    if det[1].match(line):
                        print(f"   {no:6d}: {line.strip()[:100]}")
                        n += 1
                        if n >= 10:
                            break
            else:
                print("   first lines:")
                for l in text.splitlines()[:15]:
                    print("     " + l[:100])
                print("   -> set \"object_marker\" (regex with named groups type/name) for this system in migration.config.json")


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    ap.add_argument("--inspect", nargs="*", metavar=("SYS", "PKG"))
    ap.add_argument("--apply-resolution", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    systems = [s for s in cfg.systems if cfg.fmt(s) == "chunks"]
    if not systems:
        print("UNCHUNK_OK systems=0 packages=0 objects=0 fms=0 unresolved=0 (no system has format 'chunks')")
        return 0
    if args.inspect is not None:
        inspect(cfg, systems, args.inspect[0] if args.inspect else None, args.inspect[1] if len(args.inspect) > 1 else None)
        return 0
    if args.apply_resolution:
        st = apply_resolution(cfg, systems)
        print(f"UNCHUNK_APPLY_OK applied={st['applied']} skipped={st['skipped']} invalid={st['invalid']}")
        return 0

    stats: Counter = Counter()
    unresolved_all: List[dict] = []
    unchanged: set = set()
    unres_path = cfg.work_dir / "unchunk_unresolved.json"
    old_unresolved = read_json(unres_path).get("segments", []) if unres_path.exists() and not args.force else []
    fmt_path = cfg.work_dir / "unchunk_format.json"
    formats: Dict[str, dict] = read_json(fmt_path) if fmt_path.exists() and not args.force else {}
    for system in systems:
        root = cfg.resolve(system["root"])
        if not root.exists():
            log(f"[{system['id']}] ERROR root does not exist: {root}")
            return 2
        out_dir = cfg.unchunked_dir(system)
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "_manifest.jsonl"
        old_rows = read_jsonl(manifest_path) if manifest_path.exists() and not args.force else []
        old_sig = {r["package"]: r.get("sig") for r in old_rows if r.get("source") == "parser"}
        rows: List[dict] = []
        pkg_dirs = [p for p in sorted(root.iterdir()) if p.is_dir()]
        log(f"[{system['id']}] {len(pkg_dirs)} package folders under {root}")
        for pkg_dir in pkg_dirs:
            process_package(system, pkg_dir, out_dir, system.get("chunk_glob", "*.abapchunk"), system.get("object_marker"),
                            stats, unresolved_all, formats, args.force, rows, old_sig, unchanged)
        # keep llm-resolved rows from a previous run for packages that were not rebuilt
        rebuilt = {r["package"] for r in rows if r.get("source") == "parser" and r.get("sig") not in old_sig.values()}
        rows.extend(r for r in old_rows if r.get("source") == "llm" and r["package"] not in rebuilt and not any(
            x["type"] == r["type"] and x["name"] == r["name"] and x["package"] == r["package"] for x in rows))
        write_jsonl(manifest_path, rows)
        stats["systems"] += 1
    # unchanged packages keep the unresolved segments they still had from the previous run
    unresolved_all.extend(u for u in old_unresolved if f"{u['system']}|{u['package']}" in unchanged)
    stats["unresolved"] = len(unresolved_all)
    write_json(fmt_path, formats)
    write_json(unres_path, {"segments": unresolved_all})
    log(f"unchunk: {dict(stats)}")
    print(f"UNCHUNK_OK systems={stats['systems']} packages={stats['packages'] + stats['packages_unchanged']} "
          f"objects={stats['objects']} fms={stats['fms']} unresolved={stats['unresolved']} "
          f"unchanged_packages={stats['packages_unchanged']} out={cfg.work_dir / 'unchunked'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
