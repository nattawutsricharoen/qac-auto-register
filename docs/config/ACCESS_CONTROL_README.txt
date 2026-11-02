QAC Auto Register - Central Access Control v6
================================================

Header:
ip,name,status,tab1_enable,tab1_show,tab2_enable,tab2_show,tab3_enable,tab3_show,tab4_enable,tab4_show,tab5_enable,tab5_show,tab6_enable,tab6_show,settings_show

Tab mapping:
tab1 = Auto Register
tab2 = Alarm Import
tab3 = OCR NG Import
tab4 = Production Output Import
tab5 = Daily Document
tab6 = Sample Register

Rules:
show=0              hidden
show=1 + enable=0   visible but disabled
show=1 + enable=1   usable
settings_show=1     Settings visible

Sample Register security:
- Sample Register is controlled by tab6_show/tab6_enable.
- Prepare/Register actions also perform a backend permission check.
- v5 or older access CSV files remain readable, but Sample Register is fail-closed
  (hidden and disabled) until tab6_enable/tab6_show are explicitly added.

Upgrade existing central v5 CSV:
1. Add tab6_enable and tab6_show immediately before settings_show.
2. Set both fields explicitly per machine/IP. Example: 1,1 = visible and usable.
3. Do not remove existing permission columns.

Unknown machine:
The program appends status=pending with every permission field available
in the current CSV set to 0.

Production central path configured by default:
\\159.228.251.190\dsst-pr\PD 1 (Production Inflator & Coolant)\Public\03. Inflator 2 (HYBRID)\00. Line data LE type\VBA_Code_Data_Edit\Auto_QAC_Register\access_control.csv
