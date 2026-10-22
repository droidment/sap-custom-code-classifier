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
