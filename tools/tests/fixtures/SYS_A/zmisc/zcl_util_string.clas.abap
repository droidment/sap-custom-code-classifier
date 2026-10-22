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
