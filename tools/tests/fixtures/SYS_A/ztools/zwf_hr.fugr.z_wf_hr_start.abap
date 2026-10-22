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
