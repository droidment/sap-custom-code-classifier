"""Create two tiny synthetic abapGit exports (SYS_A, SYS_B) under tools/tests/fixtures/.

The fixtures cover: an HR timesheet report (CATSDB + PNP), a Z-table used only by it (propagation),
a helper class with no evidence (propagation), an HR workflow function group (SWW_* + PA0001),
an MM purchasing BAdI class (EKKO/EKPO + IF_EX_ME_PROCESS_PO_CUST), an FI posting report
(BAPI_ACC_DOCUMENT_POST), an ambiguous class (FI + MM evidence -> needs_llm), one object present in
both systems with diverged source, and one identical copy.

Usage:  py tools/tests/make_fixtures.py
"""
from __future__ import annotations

from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"


def w(rel: str, text: str) -> None:
    p = FIX / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")


def devc(desc: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_DEVC" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values><DEVC><CTEXT>{desc}</CTEXT></DEVC></asx:values>
 </asx:abap>
</abapGit>"""


def prog_xml(name: str, title: str, ldb: str = "") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_PROG" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <PROGDIR><NAME>{name}</NAME><SUBC>1</SUBC><LDBNAME>{ldb}</LDBNAME><RLOAD>E</RLOAD><FIXPT>X</FIXPT><UCCHECK>X</UCCHECK></PROGDIR>
   <TPOOL><item><ID>R</ID><ENTRY>{title}</ENTRY><LENGTH>{len(title)}</LENGTH></item></TPOOL>
  </asx:values>
 </asx:abap>
</abapGit>"""


def clas_xml(name: str, desc: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_CLAS" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values><VSEOCLASS><CLSNAME>{name}</CLSNAME><LANGU>E</LANGU><DESCRIPT>{desc}</DESCRIPT><STATE>1</STATE><CLSCCINCL>X</CLSCCINCL><FIXPT>X</FIXPT><UNICODE>X</UNICODE></VSEOCLASS></asx:values>
 </asx:abap>
</abapGit>"""


def tabl_xml(name: str, desc: str, fields) -> str:
    rows = "".join(f"<DD03P><TABNAME>{name}</TABNAME><FIELDNAME>{f}</FIELDNAME><ROLLNAME>{r}</ROLLNAME></DD03P>" for f, r in fields)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_TABL" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values><DD02V><TABNAME>{name}</TABNAME><DDLANGUAGE>E</DDLANGUAGE><TABCLASS>TRANSP</TABCLASS><DDTEXT>{desc}</DDTEXT></DD02V><DD03P_TABLE>{rows}</DD03P_TABLE></asx:values>
 </asx:abap>
</abapGit>"""


def fugr_xml(name: str, desc: str, fms) -> str:
    items = "".join(f"<item><FUNCNAME>{fn}</FUNCNAME><SHORT_TEXT>{st}</SHORT_TEXT></item>" for fn, st in fms)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_FUGR" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values><AREAT>{desc}</AREAT><INCLUDES><SOBJ_NAME>L{name}TOP</SOBJ_NAME><SOBJ_NAME>SAPL{name}</SOBJ_NAME></INCLUDES><FUNCTIONS>{items}</FUNCTIONS></asx:values>
 </asx:abap>
</abapGit>"""


HR_TS_REPORT = """
*&---------------------------------------------------------------------*
*& Report ZHR_TS_REPORT
*& Weekly timesheet hours per employee for the HR time administrators
*&---------------------------------------------------------------------*
REPORT zhr_ts_report MESSAGE-ID zhr.
TABLES: pernr.
INFOTYPES: 0001, 0002.
DATA: lt_cats TYPE TABLE OF catsdb,
      ls_log  TYPE zhrts_log,
      lo_util TYPE REF TO zcl_util_string.
SELECT-OPTIONS: s_date FOR sy-datum.
GET pernr.
  rp_provide_from_last p0001 space pn-begda pn-endda.
  SELECT * FROM catsdb INTO TABLE lt_cats
    WHERE pernr = pernr-pernr AND workdate IN s_date AND status = '30'.
  LOOP AT lt_cats INTO DATA(ls_cats).
    ls_log-pernr = ls_cats-pernr.
    ls_log-hours = ls_cats-catshours.
    ls_log-text  = zcl_util_string=>pad_left( iv_text = ls_cats-rproj iv_len = 24 ).
    MODIFY zhrts_log FROM ls_log.
  ENDLOOP.
  CALL FUNCTION 'CATS_READ_RECORDS'
    EXPORTING pernr = pernr-pernr.
END-OF-SELECTION.
  AUTHORITY-CHECK OBJECT 'P_ORGIN' ID 'INFTY' FIELD '0001'.
"""

UTIL_CLASS = """
CLASS zcl_util_string DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    CLASS-METHODS pad_left IMPORTING iv_text TYPE string iv_len TYPE i RETURNING VALUE(rv_text) TYPE string.
ENDCLASS.
CLASS zcl_util_string IMPLEMENTATION.
  METHOD pad_left.
    rv_text = iv_text.
    WHILE strlen( rv_text ) < iv_len.
      rv_text = | { rv_text }|.
    ENDWHILE.
  ENDMETHOD.
ENDCLASS.
"""

PO_CHECK_A = """
*" Purchase order checks for company A: block POs above approval limit
CLASS zcl_po_check DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    INTERFACES if_ex_me_process_po_cust.
    METHODS check_limit IMPORTING is_ekko TYPE ekko it_ekpo TYPE STANDARD TABLE OF ekpo RETURNING VALUE(rv_ok) TYPE abap_bool.
ENDCLASS.
CLASS zcl_po_check IMPLEMENTATION.
  METHOD check_limit.
    DATA lv_total TYPE ekpo-netwr.
    LOOP AT it_ekpo INTO DATA(ls_ekpo).
      lv_total = lv_total + ls_ekpo-netwr.
    ENDLOOP.
    SELECT SINGLE * FROM ekko INTO @DATA(ls_ekko) WHERE ebeln = @is_ekko-ebeln.
    rv_ok = xsdbool( lv_total < 50000 ).
    CALL FUNCTION 'BAPI_PO_GETDETAIL1' EXPORTING purchaseorder = is_ekko-ebeln.
  ENDMETHOD.
  METHOD if_ex_me_process_po_cust~check.
    MESSAGE e001(zmm) WITH 'PO limit exceeded'.
  ENDMETHOD.
ENDCLASS.
"""

PO_CHECK_B = PO_CHECK_A.replace("company A", "company B").replace("50000", "75000").replace(
    "ENDCLASS.\n", "ENDCLASS.\n", 1) + """
* company B addition: also check the requisition
"""

WF_TOP = """
FUNCTION-POOL zwf_hr MESSAGE-ID zwf.
TABLES: pa0001.
"""
WF_FM = """
FUNCTION z_wf_hr_start.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IV_PERNR) TYPE  PERNR_D
*"----------------------------------------------------------------------
* Start the HR approval workflow for a personnel change request
  DATA lt_cont TYPE TABLE OF swr_cont.
  SELECT SINGLE * FROM pa0001 INTO @DATA(ls_p0001) WHERE pernr = @iv_pernr AND endda >= @sy-datum.
  CALL FUNCTION 'SAP_WAPI_START_WORKFLOW'
    EXPORTING task = 'WS90000001'
    TABLES input_container = lt_cont.
  SELECT * FROM swwwihead INTO TABLE @DATA(lt_wi) WHERE wi_rh_task = 'WS90000001'.
ENDFUNCTION.
"""

FI_POST = """
*& Post intercompany accounting documents from the clearing file
REPORT zfi_post.
DATA: lt_header TYPE bapiache09, lt_items TYPE TABLE OF bapiacgl09, lt_return TYPE TABLE OF bapiret2.
SELECT * FROM bkpf INTO TABLE @DATA(lt_bkpf) WHERE bukrs = '1000' AND gjahr = @sy-datum(4).
CALL FUNCTION 'BAPI_ACC_DOCUMENT_POST'
  EXPORTING documentheader = lt_header
  TABLES accountgl = lt_items return = lt_return.
CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
"""

AMBIG = """
* Generic document helper used by finance and purchasing
CLASS zcl_doc_helper DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    METHODS get_doc IMPORTING iv_id TYPE char10 RETURNING VALUE(rv_text) TYPE string.
ENDCLASS.
CLASS zcl_doc_helper IMPLEMENTATION.
  METHOD get_doc.
    SELECT SINGLE belnr FROM bkpf INTO @DATA(lv_belnr) WHERE belnr = @iv_id.
    SELECT SINGLE ebeln FROM ekko INTO @DATA(lv_ebeln) WHERE ebeln = @iv_id.
    rv_text = |{ lv_belnr }{ lv_ebeln }|.
  ENDMETHOD.
ENDCLASS.
"""

TS_REPORT_B = HR_TS_REPORT.replace("zhr_ts_report", "zhr_ts_report_b").replace("ZHR_TS_REPORT", "ZHR_TS_REPORT_B").replace("zhrts_log", "zb_ts_log")


def main() -> None:
    # ---- SYS_A ----
    w("SYS_A/zmisc/package.devc.xml", devc("Miscellaneous developments"))
    w("SYS_A/zmisc/zhr_ts_report.prog.abap", HR_TS_REPORT)
    w("SYS_A/zmisc/zhr_ts_report.prog.xml", prog_xml("ZHR_TS_REPORT", "Timesheet hours per employee", "PNP"))
    w("SYS_A/zmisc/zhrts_log.tabl.xml", tabl_xml("ZHRTS_LOG", "Log table", [("PERNR", "PERNR_D"), ("HOURS", "CATSHOURS"), ("TEXT", "CHAR40")]))
    w("SYS_A/zmisc/zcl_util_string.clas.abap", UTIL_CLASS)
    w("SYS_A/zmisc/zcl_util_string.clas.xml", clas_xml("ZCL_UTIL_STRING", "String helpers"))
    w("SYS_A/zmisc/zcl_po_check.clas.abap", PO_CHECK_A)
    w("SYS_A/zmisc/zcl_po_check.clas.xml", clas_xml("ZCL_PO_CHECK", "PO approval limit check"))
    w("SYS_A/zmisc/zcl_doc_helper.clas.abap", AMBIG)
    w("SYS_A/zmisc/zcl_doc_helper.clas.xml", clas_xml("ZCL_DOC_HELPER", "Document helper"))
    w("SYS_A/ztools/package.devc.xml", devc("Tools"))
    w("SYS_A/ztools/zwf_hr.fugr.xml", fugr_xml("ZWF_HR", "HR workflow starters", [("Z_WF_HR_START", "Start HR approval workflow")]))
    w("SYS_A/ztools/zwf_hr.fugr.lzwf_hrtop.abap", WF_TOP)
    w("SYS_A/ztools/zwf_hr.fugr.saplzwf_hr.abap", "INCLUDE lzwf_hrtop.\nINCLUDE lzwf_hruxx.")
    w("SYS_A/ztools/zwf_hr.fugr.z_wf_hr_start.abap", WF_FM)
    # ---- SYS_B ----
    w("SYS_B/zdev/package.devc.xml", devc("Development objects"))
    w("SYS_B/zdev/zcl_po_check.clas.abap", PO_CHECK_B)
    w("SYS_B/zdev/zcl_po_check.clas.xml", clas_xml("ZCL_PO_CHECK", "PO approval limit check (B)"))
    w("SYS_B/zdev/zfi_post.prog.abap", FI_POST)
    w("SYS_B/zdev/zfi_post.prog.xml", prog_xml("ZFI_POST", "Post IC documents"))
    w("SYS_B/zdev/zhr_ts_report_b.prog.abap", TS_REPORT_B)
    w("SYS_B/zdev/zhr_ts_report_b.prog.xml", prog_xml("ZHR_TS_REPORT_B", "Timesheet hours (B)", "PNP"))
    w("SYS_B/zdev/zb_ts_log.tabl.xml", tabl_xml("ZB_TS_LOG", "Log table B", [("PERNR", "PERNR_D"), ("HOURS", "CATSHOURS")]))
    w("SYS_B/zdev/zcl_util_string.clas.abap", UTIL_CLASS)
    w("SYS_B/zdev/zcl_util_string.clas.xml", clas_xml("ZCL_UTIL_STRING", "String helpers"))
    # ---- SYS_C: the SYS_A objects as a chained chunk export with marker lines ----
    stream = "\n".join([
        "*** OBJECT PROG ZHR_TS_REPORT ***", HR_TS_REPORT.strip(),
        "*** OBJECT CLAS ZCL_UTIL_STRING ***", UTIL_CLASS.strip(),
        "*** OBJECT CLAS ZCL_PO_CHECK ***", PO_CHECK_A.strip().split("CLASS zcl_po_check IMPLEMENTATION.")[0].rstrip(),
        "*** OBJECT CLAS ZCL_PO_CHECK ***", "CLASS zcl_po_check IMPLEMENTATION." + PO_CHECK_A.strip().split("CLASS zcl_po_check IMPLEMENTATION.")[1],
        "*** OBJECT CLAS ZCL_DOC_HELPER ***", AMBIG.strip(),
        "*** OBJECT FUGR ZWF_HR ***", WF_TOP.strip(),
        "*** OBJECT FUNC Z_WF_HR_START ***", WF_FM.strip(),
        "*** OBJECT ***", "* fragment with no usable name", "DATA lv_x TYPE i.", "lv_x = 1.",
    ]) + "\n"
    size = 900  # small chunks so objects are cut across files
    for i in range(0, len(stream), size):
        p = FIX / f"SYS_C/zchunked/z1_{i // size + 1:04d}.abapchunk"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(stream[i: i + size], encoding="utf-8", newline="")   # raw: a chunk may end mid-line
    # ---- SYS_D: '###OBJECT SYS:TYPE:NAME' export with ###END_OBJECT and * ###END_PROGRAM lines ----
    def hobj(otype: str, name: str, body: str, prog: str) -> str:
        return (f"###OBJECT          D66:{otype}:{name}     {otype}    {name}\n" + body.strip() + "\n"
                f"* ###END_PROGRAM {prog}\n###END_OBJECT\n")
    stream = (
        hobj("PROG", "ZD_REPORT", HR_TS_REPORT.replace("zhr_ts_report", "zd_report"), "ZD_REPORT")
        + hobj("FUNC", "Z_D_AUTH_CHECK", "FUNCTION z_d_auth_check.\n*\"  Checks authorization objects\n"
               "  AUTHORITY-CHECK OBJECT 'S_TCODE' ID 'TCD' FIELD iv_tcode.\n  SELECT SINGLE * FROM usr02 INTO @DATA(ls_u) WHERE bname = @sy-uname.\nENDFUNCTION.", "SAPLZDFG")
        + hobj("FUNC", "Z_D_AUTH_LOG", "FUNCTION z_d_auth_log.\n*\"  Logs authorization failures\n"
               "  INSERT zd_auth_log FROM @is_log.\nENDFUNCTION.", "SAPLZDFG")
        + hobj("CLAS", "ZCL_D_HELPER", UTIL_CLASS.replace("zcl_util_string", "zcl_d_helper"), "ZCL_D_HELPER=================CP")
    )
    size = 700
    for i in range(0, len(stream), size):
        p = FIX / f"SYS_D/zhash/d1_{i // size + 1:04d}.abapchunk"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(stream[i: i + size], encoding="utf-8", newline="")
    print(f"fixtures written under {FIX}")


if __name__ == "__main__":
    main()
