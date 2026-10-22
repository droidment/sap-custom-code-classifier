*& Post intercompany accounting documents from the clearing file
REPORT zfi_post.
DATA: lt_header TYPE bapiache09, lt_items TYPE TABLE OF bapiacgl09, lt_return TYPE TABLE OF bapiret2.
SELECT * FROM bkpf INTO TABLE @DATA(lt_bkpf) WHERE bukrs = '1000' AND gjahr = @sy-datum(4).
CALL FUNCTION 'BAPI_ACC_DOCUMENT_POST'
  EXPORTING documentheader = lt_header
  TABLES accountgl = lt_items return = lt_return.
CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'.
