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
