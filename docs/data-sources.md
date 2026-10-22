# Data sources and toolchain (verified 2026-10-17)

Every fact below was checked on 2026-10-17 with a real request, download or container run. If a download fails or a column goes missing, re-verify the line before relying on it. "Not verified" at the end lists what was not checked.

## 1. SBA PPP loan-level data (FOIA)

- **Page:** https://data.sba.gov/dataset/ppp-foia. It lists the dataset as last modified 2024-10-21, with an "Irregular" refresh. The CKAN API (`/api/3/action/package_show?id=ppp-foia`) returns 404, so file discovery scrapes the page HTML for `.csv` links.
- **Files:** 13 CSVs, about 4.5 GB in total, under `https://data.sba.gov/sites/default/files/distribution/SBA-OCA-2022-07-001/`:
  - `public_150k_plus_240930.csv` (452 MB)
  - `public_up_to_150k_1_240930.csv` to `public_up_to_150k_12_240930.csv` (270 to 415 MB each)
  - `ppp-data-dictionary.xlsx`
- **Response headers:** `ETag`, `Last-Modified` (2026-06-26), `Accept-Ranges: bytes` and `Content-Length`. HEAD works. The server does not gzip, even when the client asks for it.
- **Header row (53 columns):** LoanNumber, DateApproved, SBAOfficeCode, ProcessingMethod, BorrowerName, BorrowerAddress, BorrowerCity, BorrowerState, BorrowerZip, LoanStatusDate, LoanStatus, Term, SBAGuarantyPercentage, InitialApprovalAmount, CurrentApprovalAmount, UndisbursedAmount, FranchiseName, ServicingLenderLocationID, ServicingLenderName, ServicingLenderAddress, ServicingLenderCity, ServicingLenderState, ServicingLenderZip, RuralUrbanIndicator, HubzoneIndicator, LMIIndicator, BusinessAgeDescription, ProjectCity, ProjectCountyName, ProjectState, ProjectZip, CD, JobsReported, NAICSCode, Race, Ethnicity, UTILITIES_PROCEED, PAYROLL_PROCEED, MORTGAGE_INTEREST_PROCEED, RENT_PROCEED, REFINANCE_EIDL_PROCEED, HEALTH_CARE_PROCEED, DEBT_INTEREST_PROCEED, BusinessType, OriginatingLenderLocationID, OriginatingLender, OriginatingLenderCity, OriginatingLenderState, Gender, Veteran, NonProfit, ForgivenessAmount, ForgivenessDate.
- **Quirks seen in the first rows:**
  - `BorrowerState` can be blank while `ProjectState` is filled.
  - Dates are `MM/DD/YYYY`.
  - Names contain commas and are quoted.
  - ZIPs are `12345-6789` or `12345`.
  - `ProcessingMethod` is `PPP` for a first draw and `PPS` for a second.
  - `BusinessAgeDescription` values include "Existing or more than 2 years old", "New Business or 2 years or less", "Change of Ownership" and "Unanswered".
  - `LoanStatus` values include "Paid in Full", "Charged Off" and "Exemption 4".

## 2. Texas Comptroller open data (Socrata, data.texas.gov)

Two datasets, both refreshed about weekly; rows were last updated on Saturday 2026-10-10 around 08:00 UTC. Use the row-level JSON API (`https://data.texas.gov/resource/<id>.json?$where=...`) for spot checks and the CSV export for downloads. JSON field names differ from the CSV headers; for example, the franchise NAICS field is literally `_621111`.

Both exports return `Content-Length: 0` on HEAD, because they are streamed. `ETag` and `Last-Modified` are identical across repeated HEADs and with or without `Accept-Encoding: gzip`. Unauthenticated HEAD requests and streaming worked. A full download has not been tried. If it gets HTTP 429, register a free Socrata app token and send it as `X-App-Token`.

### Active Franchise Taxpayers, id `9cir-efmm`

- 3,486,216 rows covering 3,486,185 distinct taxpayer numbers. The 31 duplicated numbers are exact or near duplicates that differ only in charter date or status.
- CSV export: `https://data.texas.gov/api/views/9cir-efmm/rows.csv?accessType=DOWNLOAD`. Metadata, including `rowsUpdatedAt`: `https://data.texas.gov/api/views/9cir-efmm.json`.
- Code sheet: "Franchise Layout.docx", attached to the dataset as asset `297f2282-33fe-4e7b-86de-10f6ae5f07e3`.
- CSV header exactly as served, stray spaces included: `Taxpayer Number,Taxpayer Name,Taxpayer Address,Taxpayer City,Taxpayer State,Taxpayer Zip,Taxpayer County Code,Taxpayer Organizational Type,Record Type Code,Responsibility Beginning Date,  Secretary of State (SOS) or COA File Number,SOS Charter Date,SOS Status Date ,SOS Status Code,Right to Transact Business Code,Current Exempt Reason Code,Exempt Begin Date,NAICS Code`. Dates are `MM/DD/YYYY`.
- **Codes that matter**
  - **Taxpayer Organizational Type:**
    - `CT` Texas profit corporation
    - `CL` Texas LLC
    - `CF` foreign profit corporation
    - `CI` foreign LLC
    - `CP` Texas professional corporation
    - `AP` Texas professional association
    - `PL` Texas limited partnership
    - `CN` Texas nonprofit
    - `PB` and `PI` general partnerships
    - `S` sole proprietorship
    - `IS` individual sole owner
  - **Record Type Code:**
    - `U` SOS file number
    - `V` SOS certificate of authority
    - `X` Comptroller-assigned, with no charter and a blank charter date
  - **SOS Status Code:**
    - `A` active
    - `R` reinstated
    - `F` forfeited franchise tax
    - `D` dissolved
    - `T` terminated
    - `M` merger
    - `W` withdrawn
    - `C` converted
  - **Right to Transact Business Code:**
    - `A` active
    - `D` active but eligible for termination
    - `N` forfeited
    - `I` involuntarily ended
    - `U` not established
    - blank: ended
- **Taxpayer Number:** 11 digits. Prefix `1` means `1`, then the 9-digit federal EIN, then a check digit. Prefix `3` means a Comptroller-assigned base with no EIN. Verified on two companies:
  - Texas Instruments (EIN 75-0289970) is `17502899705`, with charter date 1938-12-31.
  - Southwest Airlines (EIN 74-1563240) is `17415632409`, with charter date 1967-03-09.

  So `ein = substr(taxpayer_number, 2, 9)` when the number starts with `1`.
- **NAICS** is sparse: only 2,334 rows carry 238220, plumbing and HVAC contractors. Prefer the PPP NAICS.
- **Scope gap:** sole proprietorships and general partnerships owe no franchise tax, so most are absent. The sales-tax dataset covers some of them.

### Active Sales Tax Permit Holders, id `jrea-zgmq`

- 890,307 rows, one per outlet (location), covering 705,284 distinct taxpayers.
- CSV export: `https://data.texas.gov/api/views/jrea-zgmq/rows.csv?accessType=DOWNLOAD`.
- Header: `Taxpayer Number,Taxpayer Name,Taxpayer Address,Taxpayer City,Taxpayer State,Taxpayer Zip Code,Taxpayer County Code,Taxpayer Organization Type,Outlet Number,Outlet Name,Outlet Address,Outlet City,Outlet State,Outlet Zip Code,Outlet County Code,Outlet NAICS Code,Outlet Inside/Outside City Limits Indicator,Outlet Permit Issue Date,Outlet First Sales Date`. Dates are `MM/DD/YYYY`.
- `Outlet Name` is the trade name (DBA). `Outlet First Sales Date` is an independent signal of business age. Taxpayer numbers follow the same rules as above.

## 3. DOL EBSA Form 5500 datasets

- **Page:** https://www.dol.gov/agencies/ebsa/about-ebsa/our-activities/public-disclosure/foia/form-5500-datasets. The page says the datasets are "typically updated around the first of each month".
- **URLs** for form year `YYYY` (2022 to 2025 exist today):
  - `https://askebsa.dol.gov/FOIA%20Files/YYYY/Latest/F_5500_YYYY_Latest.zip`
  - `https://askebsa.dol.gov/FOIA%20Files/YYYY/Latest/F_5500_SF_YYYY_Latest.zip`
  - The column layout is at the same path with `_layout.txt` in place of `.zip`.

  The host 301-redirects to `www.askebsa.dol.gov`. Responses carry `ETag`, `Last-Modified` (2026-09-30 for the 2024 files), `Accept-Ranges` and `Content-Length`.
- **Zip contents (2024):**

  | Zip | Zipped | Member | Unzipped |
  | --- | --- | --- | --- |
  | `F_5500_SF_2024_Latest.zip` | 136 MB | `f_5500_sf_2024_latest.csv` | 600 MB |
  | `F_5500_2024_Latest.zip` | 28.6 MB | `f_5500_2024_latest.csv` | 137 MB |

  Each zip holds exactly one lowercase CSV plus a `_layout.txt`.
- **Latest vs. All:** "Latest" keeps only the latest version of each filing, with amendments collapsed; "All" keeps every submission. Use Latest. Each dataset is keyed to the form year printed on the form, and filings for plan year N mostly arrive during N+1.
- **CSV format:**
  - Every field is quoted.
  - Dates are ISO `YYYY-MM-DD`; for example, `PLAN_EFF_DATE` reads `1991-07-07`.
  - Signature dates are timestamps with an offset, such as `2025-01-03T14:21:17-0600`.
  - EINs are 9 digits. ZIPs are 5 or 9 digits with no dash. Phone numbers are 10 digits.
  - The pension benefit code field packs 2-character codes, digit then letter, for example `2E2J2K2F2G3D3H`.
- **Fields used from Form 5500-SF:** ACK_ID, SF_PLAN_YEAR_BEGIN_DATE, SF_PLAN_NAME, SF_PLAN_EFF_DATE, SF_SPONSOR_NAME, SF_SPONSOR_DFE_DBA_NAME, SF_SPONS_US_ADDRESS1, SF_SPONS_US_CITY, SF_SPONS_US_STATE, SF_SPONS_US_ZIP, SF_SPONS_EIN, SF_SPONS_PHONE_NUM, SF_BUSINESS_CODE, SF_ADMIN_NAME, SF_ADMIN_NAME_SAME_SPON_IND, SF_TOT_PARTCP_BOY_CNT, SF_TOT_ACT_PARTCP_BOY_CNT, SF_TYPE_PENSION_BNFT_CODE, SF_SPONS_SIGNED_NAME, SF_SPONS_MANUAL_SIGNED_NAME, SF_ADMIN_SIGNED_NAME, SF_ADMIN_MANUAL_SIGNED_NAME, DATE_RECEIVED.
- **Fields used from Form 5500:** ACK_ID, FORM_PLAN_YEAR_BEGIN_DATE, PLAN_NAME, PLAN_EFF_DATE, SPONSOR_DFE_NAME, SPONS_DFE_MAIL_US_ADDRESS1, SPONS_DFE_MAIL_US_CITY, SPONS_DFE_MAIL_US_STATE, SPONS_DFE_MAIL_US_ZIP, SPONS_DFE_EIN, SPONS_DFE_PHONE_NUM, BUSINESS_CODE, ADMIN_NAME, ADMIN_NAME_SAME_SPON_IND, TOT_PARTCP_BOY_CNT, TOT_ACT_PARTCP_BOY_CNT, TYPE_PENSION_BNFT_CODE, SPONS_SIGNED_NAME, SPONS_MANUAL_SIGNED_NAME, ADMIN_SIGNED_NAME, ADMIN_MANUAL_SIGNED_NAME, DATE_RECEIVED.
- **Pension benefit codes:** `1A` to `1I` are defined benefit plans (`1A` traditional, `1C` cash balance). `2A` to `2T` are defined contribution plans (`2E` profit sharing, `2J` 401(k)). A defined benefit plan with few participants suggests an older owner saving hard for retirement.
- **Texas, form year 2024, by sponsor mailing state:**

  | Measure | 5500-SF | 5500 |
  | --- | --- | --- |
  | Filings | 44,946 | 17,231 |
  | Distinct EINs | 41,514 | |
  | Filings with a defined benefit code | 2,153 | |
  | Filings whose plan took effect 30 or more years ago | 3,771 | 3,452 |
  | Sponsor signed name filled | 3,811 | 1,475 |
  | Admin signed name filled | 35,725 | 12,249 |
  | Administrator is the sponsor (indicator `1`) | 39,392 | |
  | Sponsor phone filled | 44,801 | |

  The administrator indicator is `1` or blank. Nationally, the 2024 SF file has 799,188 filings and 728,741 EINs.
- **Sentinel:** Texas Instruments' EIN `750289970` appears 5 times in the 2024 Form 5500 file. NORTH TEXAS COMPRESSION, INC. (EIN `470871940`, Bridgeport TX) is the first row of the 2024 SF file.

## 4. Google Places API (New), phase 2 only, not verified

- Text Search and Place Details return at most 5 reviews per place. Reviews belong to the most expensive SKU; third-party price tables from July 2026 show about $25 to $35 per 1,000 calls. Field masks keep the cheaper calls cheap. Check Google's own price list before enabling this.

## 5. National PPP and Form 5500 (measured 2026-10-17)

Measured with host DuckDB over the raw files already downloaded for Texas.

- **PPP, all states.**
  - 11,468,210 loans across 50 states, DC, PR, GU, VI, MP, AS, and a handful of junk codes (`NA` 111, `AE` 4, `AP` 1, `FI` 1).
  - 363 loans are unusable: 197 have no ZIP, 166 have no name after normalization, and 28 have no state.
  - The usable loans form 9,192,675 `(norm_name, zip5)` keys. 119 keys have loans in two states.
  - Staging all states into a temp table took 11.6 s and peaked at 4.3 GB RSS.
  - Loans per state are in section 11's table. The largest are CA 1,270,593, FL 983,321, TX 938,551, NY 734,799, IL 620,021 and GA 553,311.
- **Form 5500, all states, form years 2022 to 2025.**
  - 1,054,672 sponsor EINs, one row per EIN. 152,125 of them have a plan effective 30 or more years before 2026-10-17.
  - Sponsors by latest mailing state: CA 179,823, NY 74,299, TX 65,347, FL 61,856, OH 41,357, IL 41,280, PA 39,066, NJ 37,383, MA 32,861, GA 31,403.
- **PPP to Form 5500 directly, in Texas, by `(norm_name, zip5)`.**
  - 23,413 PPP businesses match exactly one sponsor.
  - 2,640 of them have a 30+ year plan, but only 333 of those were not already matched through the Texas registry.
  - So plan sponsors alone date about a tenth as many businesses as a state registry does.
- **Plan sponsors without a PPP loan, nationally, 2022 to 2025.** This measurement is why product decision 16 counts every source's businesses, not only PPP borrowers.
  - 616,842 of 1,054,672 sponsor EINs (58%) have no PPP key with the same `(norm_name, zip5)`.
  - 79,491 of those have a plan 30 or more years old.
  - 613,212 have an industry code, and 544,724 report 1 to 500 active participants.
  - It is an upper bound: some took PPP under another name or address.

## 6. Form 5500, form years 2009 to 2021 (verified by request)

- Every year from 2009 to 2025 returns 200 for both forms. 2008 and 2026 return 404. All files are dated 2026-09-30.
- Use `https://www.askebsa.dol.gov/FOIA%20Files/...`. The bare host's 301 sends a raw space in `Location`.

| Form year | `F_5500_<y>_Latest.zip` bytes | `F_5500_SF_<y>_Latest.zip` bytes |
| --- | --- | --- |
| 2009 | 51,526,911 | 72,409,517 |
| 2010 | 40,945,611 | 82,067,321 |
| 2012 | 35,079,727 | 84,263,904 |
| 2015 | 33,792,530 | 93,486,267 |
| 2018 | 30,943,710 | 99,642,226 |
| 2021 | 30,631,932 | 109,814,467 |

2011, 2013, 2014, 2016, 2017, 2019 and 2020 were not requested.

- **Layouts** are named `F_5500_<y>_Latest_layout.txt` and `F_5500_SF_<y>_Latest_layout.txt`. Every older layout is a strict subset of 2022, with no renames, so columns must be read by header name.
- **Present every year from 2009:**
  - `SF_SPONS_EIN`, `SF_PLAN_EFF_DATE`, `SF_SPONSOR_NAME`, `SF_SPONS_US_STATE`, `SF_SPONS_US_ZIP`, `SF_BUSINESS_CODE`, `SF_SPONS_SIGNED_NAME`, `SF_ADMIN_SIGNED_NAME`
  - `SPONS_DFE_EIN`, `PLAN_EFF_DATE`, `SPONSOR_DFE_NAME`, `SPONS_DFE_MAIL_US_STATE`, `SPONS_DFE_MAIL_US_ZIP`, `BUSINESS_CODE`, `SPONS_SIGNED_NAME`
- **Missing in older years:**
  - SF 2009 and 2010 lack `SF_SPONS_LOC_US_*` and `SF_PREPARER_*`.
  - The main form for 2009 and 2010 lacks `PREPARER_*`.
  - `*_MANUAL_SIGNED_NAME` is absent in 2015 and earlier. `SF_ADMIN_MANUAL_SIGNED_NAME` exists from 2015, and the sponsor and main-form versions by 2018.
  - 2018 lacks only `ADOPTED_PLAN_PERM_SEC_ACT`.
  - 2021 is identical to 2022.

## 7. SBA 7(a) and 504 FOIA loans (verified by request)

- **Page:** https://data.sba.gov/dataset/7a-504-foia. It lists six CSVs plus `7a_504_foia_data_dictionary.xlsx`, under `https://data.sba.gov/sites/default/files/uploaded_resources/`. Every file answers HEAD with `ETag`, `Last-Modified` (2026-07-21) and `Content-Length`.

  | File | Bytes |
  | --- | --- |
  | `FOIA_7a_FY1991_FY1999_asof_260630.csv` | 146,416,885 |
  | `FOIA_7a_FY2000_FY2009_asof_260630.csv` | 318,425,094 |
  | `FOIA_7a_FY2010_FY2019_asof_260630.csv` | 255,101,999 |
  | `FOIA_7a_FY2020_Present_asof_260630.csv` | 181,130,871 |
  | `FOIA_504_FY1991_FY2009_asof_260630.csv` | 53,616,900 |
  | `FOIA_504_FY2010_Present_asof_260630.csv` | 59,412,738 |

  The suffix `asof_260630` changes with each quarterly release.
- **7(a) header**, the same in all four files:

  `"AsOfDate","Program","LocationID","BorrName","BorrStreet","BorrCity","BorrState","BorrZip","BankName","BankFDICNumber","BankNCUANumber","BankStreet","BankCity","BankState","BankZip","GrossApproval","SBAGuaranteedApproval","ApprovalDate","ApprovalFY","FirstDisbursementDate","ProcessingMethod","InitialInterestRate","FixedorVariableInterestInd","TermInMonths","NaicsCode","NaicsDescription","FranchiseCode","FranchiseName","ProjectCounty","ProjectState","SBADistrictOffice","CongressionalDistrict","BusinessType","BusinessAge","LoanStatus","PaidInFullDate","ChargeOffDate","GrossChargeOffAmount","RevolverStatus","JobsSupported","CollateralInd","SoldSecMrktInd"`
- **504 header**, the same in both files:

  `"AsOfDate","Program","LocationID","BorrName","BorrStreet","BorrCity","BorrState","BorrZip","CDC_Name","CDC_Street","CDC_City","CDC_State","CDC_Zip","ThirdPartyLender_Name","ThirdPartyLender_City","ThirdPartyLender_State","ThirdPartyDollars","GrossApproval","ApprovalDate","ApprovalFY","FirstDisbursementDate","ProcessingMethod","TermInMonths","NaicsCode","NaicsDescription","FranchiseCode","FranchiseName","ProjectCounty","ProjectState","SBADistrictOffice","CongressionalDistrict","BusinessType","BusinessAge","LoanStatus","PaidInFullDate","ChargeOffDate","GrossChargeOffAmount","JobsSupported","CollateralInd"`
- **Format:**
  - Every field is quoted, and empty fields are bare.
  - Dates are ISO.
  - Amounts look like `"250000.0"`.
  - `Program` is `" 7A"` with a leading space, or `"504"`.
  - `BusinessAge` in the 1990s has fine buckets such as "Less than 4 years old but at least 3".
  - Some 1990s borrower names are people.
- **The two 1990s files:** 448,099 loans, 228,746 of them approved on or before 1996-10-17. Approval dates run from 1990-10-01 to 2009-09-30. 6 rows lack a name or ZIP.
  - Matched exactly on `(norm_name, zip5)` against national PPP, 38,017 PPP keys have an SBA loan.
  - 13,988 of those have one approved 30 or more years ago, and 11,102 of them are in states with no free registry.
- **Sentinel:** COPYTRON, INC., 2588 VANCE DRIVE, MT AIRY MD 21771, 7(a), approved 1990-10-01. It is the second row of the FY1991 to FY1999 file.

## 8. SAM.gov public entity extract (verified by request)

- **List:** `https://sam.gov/api/prod/fileextractservices/v1/api/listfiles?domain=Entity%20Registration/Public%20V2&privacy=Public`. On 2026-10-17 it listed `SAM_PUBLIC_MONTHLY_V2_20261005.ZIP` and `SAM_PUBLIC_UTF-8_MONTHLY_V2_20261005.ZIP`, both dated Oct 04, 2026. The listing describes them as "a refresh file for all active registration records and those which expired in the past six months".
- **Download:** `https://sam.gov/api/prod/fileextractservices/v1/api/download/Entity%20Registration/Public%20V2/<file>?privacy=Public`.
  - It answers 303 to a signed S3 URL that expires after 45 minutes. HEAD on that URL returns 403; GET works.
  - No key and no login are needed. This is the endpoint the website itself uses, and it is undocumented.
  - The documented `api.sam.gov/data-services/v1/extracts` needs a key tied to an account (10 requests a day without a role).
- **File:** the 20261005 file is 149,228,825 bytes, a zip inside a zip. The inner member is a 553 MB pipe-delimited `.dat` with 142 fields per record.
  - The first line is `BOF PUBLIC V2 00000000 20261005 0905712 0008359`, where 905712 is the record count. The last line starts with `EOF`.
  - The fields are UEI, CAGE, the active or expired code, legal name, DBA, physical address, city, state, ZIP+4, entity start date (field 25, `YYYYMMDD`), structure, primary NAICS, the NAICS list, and point-of-contact names. There is no EIN.
- **Counts:** 905,712 records, 868,763 in the US. 868,161 US records have a start date. 247,395 US entities started in 1996 or earlier, and 235,277 of those are active.
- **Releases:** the public monthly file comes on the first Sunday of the month. Daily entity files are FOUO and not public.
- **Caveats:** only entities registered for federal contracts or grants are included, and the start date is self-reported.

## 9. FMCSA Company Census (verified by request)

- **Export:** `https://data.transportation.gov/api/views/az4n-8mr2/rows.csv?accessType=DOWNLOAD`, titled "Company Census File". Rows were updated on 2026-10-16. HEAD returns `ETag`, `Last-Modified: Fri, 16 Oct 2026 10:20:13 GMT` and `Content-Length: 0`, because the export is streamed. No licence is stated; it is US DOT public data.
- **Header as served:**

  `MCS150_DATE,ADD_DATE,STATUS_CODE,DOT_NUMBER,DUN_BRADSTREET_NO,PHY_OMC_REGION,SAFETY_INV_TERR,CARRIER_OPERATION,BUSINESS_ORG_ID,MCS150_MILEAGE,MCS150_MILEAGE_YEAR,MCS151_MILEAGE,TOTAL_CARS,MCS150_UPDATE_CODE_ID,PRIOR_REVOKE_FLAG,PRIOR_REVOKE_DOT_NUMBER,PHONE,FAX,CELL_PHONE,COMPANY_OFFICER_1,COMPANY_OFFICER_2,BUSINESS_ORG_DESC,TRUCK_UNITS,POWER_UNITS,BUS_UNITS,FLEETSIZE,REVIEW_ID,RECORDABLE_CRASH_RATE,MAIL_NATIONALITY_INDICATOR,PHY_NATIONALITY_INDICATOR,PHY_BARRIO,MAIL_BARRIO,CARSHIP,DOCKET1PREFIX,DOCKET1,DOCKET2PREFIX,DOCKET2,DOCKET3PREFIX,DOCKET3,POINTNUM,TOTAL_INTRASTATE_DRIVERS,MCSIPSTEP,MCSIPDATE,HM_Ind,INTERSTATE_BEYOND_100_MILES,INTERSTATE_WITHIN_100_MILES,INTRASTATE_BEYOND_100_MILES,INTRASTATE_WITHIN_100_MILES,TOTAL_CDL,TOTAL_DRIVERS,AVG_DRIVERS_LEASED_PER_MONTH,CLASSDEF,LEGAL_NAME,DBA_NAME,PHY_STREET,PHY_CITY,PHY_COUNTRY,PHY_STATE,PHY_ZIP,PHY_CNTY,CARRIER_MAILING_STREET,CARRIER_MAILING_STATE,CARRIER_MAILING_CITY,CARRIER_MAILING_COUNTRY,CARRIER_MAILING_ZIP,CARRIER_MAILING_CNTY,CARRIER_MAILING_UND_DATE,DRIVER_INTER_TOTAL,EMAIL_ADDRESS,REVIEW_TYPE,REVIEW_DATE,SAFETY_RATING,SAFETY_RATING_DATE,UNDELIV_PHY,CRGO_GENFREIGHT,CRGO_HOUSEHOLD,CRGO_METALSHEET,CRGO_MOTOVEH,CRGO_DRIVETOW,CRGO_LOGPOLE,CRGO_BLDGMAT,CRGO_MOBILEHOME,CRGO_MACHLRG,CRGO_PRODUCE,CRGO_LIQGAS,CRGO_INTERMODAL,CRGO_PASSENGERS,CRGO_OILFIELD,CRGO_LIVESTOCK,CRGO_GRAINFEED,CRGO_COALCOKE,CRGO_MEAT,CRGO_GARBAGE,CRGO_USMAIL,CRGO_CHEM,CRGO_DRYBULK,CRGO_COLDFOOD,CRGO_BEVERAGES,CRGO_PAPERPROD,CRGO_UTILITY,CRGO_FARMSUPP,CRGO_CONSTRUCT,CRGO_WATERWELL,CRGO_CARGOOTHR,CRGO_CARGOOTHR_DESC,OWNTRUCK,OWNTRACT,OWNTRAIL,OWNCOACH,OWNSCHOOL_1_8,OWNSCHOOL_9_15,OWNSCHOOL_16,OWNBUS_16,OWNVAN_1_8,OWNVAN_9_15,OWNLIMO_1_8,OWNLIMO_9_15,OWNLIMO_16,TRMTRUCK,TRMTRACT,TRMTRAIL,TRMCOACH,TRMSCHOOL_1_8,TRMSCHOOL_9_15,TRMSCHOOL_16,TRMBUS_16,TRMVAN_1_8,TRMVAN_9_15,TRMLIMO_1_8,TRMLIMO_9_15,TRMLIMO_16,TRPTRUCK,TRPTRACT,TRPTRAIL,TRPCOACH,TRPSCHOOL_1_8,TRPSCHOOL_9_15,TRPSCHOOL_16,TRPBUS_16,TRPVAN_1_8,TRPVAN_9_15,TRPLIMO_1_8,TRPLIMO_9_15,TRPLIMO_16,DOCKET1_STATUS_CODE,DOCKET2_STATUS_CODE,DOCKET3_STATUS_CODE`
- **Format:**
  - Dates are `YYYYMMDD`.
  - The first row is USDOT 1, FEDERAL MOTOR CARRIER SAFETY ADMINISTRATION, Washington DC 20590, added 19740601, with a test officer `john mary`.
- **Counts:** 4,518,028 carriers: `A` 2,241,706, `I` 2,274,987, `P` 1,335. 87,010 active carriers were added before 1997, and the earliest add date is 1974-06-01.
- **Meaning:** `ADD_DATE` is when the carrier entered the USDOT system, a lower bound on its age. `COMPANY_OFFICER_1` and `COMPANY_OFFICER_2` hold owner or officer names.

## 10. State business registries

These are free, anonymous bulk files, verified by request on 2026-10-17 unless a line says otherwise. Each becomes a module in `include/pipeline/states/`.

### 10.1 Florida (spec 10)

- **Server:** `sftp://sftp.floridados.gov`, login `Public`, password `PubAccess1845!`.
  - The Division of Corporations publishes this login for its free data downloads. The sunbiz.org and dos.fl.gov pages are behind Cloudflare and return 403 to scripts; a search snippet confirms the files are free, informational and as-is.
  - The SFTP banner says "UNAUTHORIZED ACCESS IS PROHIBITED".
  - Listing the server with the public login worked.
- **Quarterly full file:** `/Public/doc/quarterly/cor/cordata.zip`, 1,793,034,019 bytes, dated Oct 07. It is refreshed in January, April, July and October. Daily files are `/Public/doc/cor/YYYYMMDDc.txt`.
- **Compression:** Deflate64 (method 9). Python `zipfile` cannot read it; `funzip` worked. The members are believed to be `cordata0.txt` to `cordata9.txt`. `cordata0.txt` is 1,872,625,902 bytes, which suggests about 13M records in total.
- **Format:** fixed width, 1,440 bytes plus LF, with no header. The field offsets were checked against a real record from the 2026-10-16 daily file; they are listed in `docs/specs/10-registry-florida/spec.md`. The file includes the FEI (EIN) and up to six officers.
- **Status:** `A` or `I`, column 205. The file date is `MMDDYYYY`, columns 473 to 480.
- **Sentinel:** `444750`, RAYMOND JAMES FINANCIAL, INC., DOMP, file date 01241974, FEI 59-1517485, ZIP 33716.
- **Container:** the scheduler container's `curl` 8.14.1 lists `sftp` among its protocols (libssh2 1.11.1). It has no `unzip`, `7z`, `bsdtar` or `funzip`, and no `paramiko`.

### 10.2 New York (spec 08)

- **Dataset:** data.ny.gov `n9v6-gdp6`, "Active Corporations: Beginning 1800". Export: `https://data.ny.gov/api/views/n9v6-gdp6/rows.csv?accessType=DOWNLOAD`.
- **Rows:** 4,299,620. Rows were updated 2026-10-16; the metadata says monthly. HEAD returns `ETag` and `Last-Modified: Fri, 16 Oct 2026 11:27:11 GMT`. No licence is stated.
- **Header:**

  `DOS ID,Current Entity Name,Initial DOS Filing Date,County,Jurisdiction,Entity Type,DOS Process Name,DOS Process Address 1,DOS Process Address 2,DOS Process City,DOS Process State,DOS Process Zip,CEO Name,CEO Address 1,CEO Address 2,CEO City,CEO State,CEO Zip,Registered Agent Name,Registered Agent Address 1,Registered Agent Address 2,Registered Agent City,Registered Agent State,Registered Agent Zip,Location Name,Location Address 1,Location Address 2,Location City,Location State,Location Zip`
- **Dates:** `MM/DD/YYYY`. The row API's field names differ from the CSV header; for example the CEO is `chairman_name`.
- **Fill rates, measured:** location ZIP on 350,078 rows, DOS process ZIP on 4,218,127, CEO name on 471,965.
- **Active only.** Inactive entities are in "All Filings" (`63wc-4exh`) and "Status History" (`3gg2-jgnp`), each 21,019,152 rows.
- **Sentinel:** `30059`, INTERNATIONAL BUSINESS MACHINES CORPORATION, 1911-06-16.

### 10.3 Pennsylvania (spec 08)

- **Dataset:** data.pa.gov `xvd7-5r2c`. Export: `https://data.pa.gov/api/views/xvd7-5r2c/rows.csv?accessType=DOWNLOAD`. Public Domain, monthly. HEAD returns `ETag` and `Last-Modified: Tue, 06 Oct 2026 12:56:05 GMT`.
- **Rows:** 4,174,730 rows, one per officer, covering 2,376,226 distinct filing numbers. Current registrations only.
- **Header:**

  `Business Name,Filing Number,Address Line 1,Address Line 2,City,State,Zip,Type of Business Registration,Creation Date,Governor/Principal Officer,Last Name,Middle Name,First Name,County Name,County Code,Georeferenced Latitude & Longitude`

  The row API calls these `business_name`, `filing_number`, `creationdate`, `party_type` and so on.
- **Officer types:**

  | Type | Rows |
  | --- | --- |
  | none | 960,148 |
  | President | 813,679 |
  | Governor | 808,915 |
  | Organizer | 413,997 |
  | Treasurer | 376,907 |
  | Secretary | 225,797 |
  | Vice President | 201,406 |
  | General Partner | 69,149 |
  | Incorporator | 65,985 |
  | Member | 29,741 |
  | Owner | 13,571 |
  | MEMBER | 11,843 |
  | others | |
- **Dates:** `MM/DD/YYYY`.
  - `1753-01-01` is a placeholder on 30,976 rows, the most frequent date.
  - `1933-09-30` covers 968 filings, is not a spike, and is a real date.
- **ZIPs** are inconsistent: `16502`, `17101-1092`, `17901-0`, `0    -0`.
- **Addresses** often look like a registered office, for example 5235 N Front St, Harrisburg. That is an inference, not verified.
- **Without officers:** the one-row-per-business view `3urc-uaba` exists.
- **Sentinel:** `0000399042`, D. G. Yuengling and Son, Incorporated, 1914-04-09, Domestic Business Corporation.

### 10.4 Virginia (spec 12)

- **Source:** data.virginia.gov (CKAN), organization `state-corporate-commission`. Resources, with bytes and the date CKAN shows:

  | Resource | Bytes | Date | URL |
  | --- | --- | --- | --- |
  | Corporation, XLSX | 90,239,379 | resource last modified 2024-11-14 | https://data.virginia.gov/dataset/3c73d9b4-a544-4cd5-a25f-f522d32815f1/resource/9d79f14f-86cd-4ce2-b2da-2df005958e0d/download/corp.xlsx |
  | LLC, CSV | 420,668,445 | package metadata 2026-03-25 | https://data.virginia.gov/dataset/cdb25eb3-b177-42c6-97e9-be2b170fd778/resource/6d55efe1-1784-414a-a38e-ce1f6b4be5fe/download/llc.csv |
  | General Partnership, XLSX | 1,203,163 | 2024-11-14 | https://data.virginia.gov/dataset/9cfdd2f3-f0f8-47fd-9ce7-c7d638b8139b/resource/883ab241-c33f-40e4-892f-03d0c9dbac4a/download/gp.xlsx |
  | Officer, CSV | 63,191,470 | | https://data.virginia.gov/dataset/178aa97e-3398-4bc2-98c1-0a2ca7f6398f/resource/c72f2bcd-13f7-4b10-b9ba-d2c88802661e/download/officer.csv |

  The organization also publishes merger, amendment, PSA, reserved-name, lien-detail and business-trust files.
- **Change detection:** the downloads redirect to presigned S3 URLs. HEAD returns 403; a ranged GET returns `ETag` and `Last-Modified`. No licence is stated.
- **`llc.csv` header,** after a UTF-8 BOM:

  `EntityID,Name,Status,StatusReason,Status Date,Duration,IncorpDate,IncorpState,IndustryCode,Street1,Street2,City,State,Zip,PrinOffEffDate,RA-Name,RA-Street1,RA-Street2,RA-City,RA-State,RA-Zip,RA-EffDate,RA-Status,RA-Loc,StockInd,TotalShares,MergerInd,AssessInd,Is Series LLC,Is Protected Series,Series LLC ID`

  `corp.xlsx` has the same columns through `AssessInd`, then ends with `Stock1`.
- **`officer.csv` header:** `EntityID,OfficerLastName,OfficerFirstName,OfficerMiddleName,OfficerTitle`.
- **Quirks:**
  - Fields are space-padded, and `EntityID` starts with a tab.
  - `IncorpDate` is an Excel serial in the XLSX (6600 is 1918-01-25) and `YYYY-MM-DD` in the CSV.
  - Some LLC dates look bogus (1899-02-16).
  - `Status` is `ACTIVE` or `INACTIVE`.
  - `IndustryCode` is an SCC code, not NAICS.
  - The corporation file has 465,855 rows, including duplicates.
- **Sentinel:** `00164871`, UNIVERSAL CORPORATION, IncorpDate serial 6600 = 1918-01-25, ACTIVE.
- **Staleness:** the corporation and partnership files are a 2024 snapshot. Check with the SCC before relying on statuses.

### 10.5 Colorado (spec 08)

- **Dataset:** data.colorado.gov `4ykn-tg5h`, "Business Entities in Colorado". Export: `https://data.colorado.gov/api/views/4ykn-tg5h/rows.csv?accessType=DOWNLOAD`. Public Domain, updated daily. HEAD returns `ETag` and `Last-Modified: Fri, 16 Oct 2026 11:18:46 GMT`.
- **Rows:** 3,124,011, all statuses.
- **Header:**

  `entityid,entityname,principaladdress1,principaladdress2,principalcity,principalstate,principalzipcode,principalcountry,mailingaddress1,mailingaddress2,mailingcity,mailingstate,mailingzipcode,mailingcountry,entitystatus,jurisdictonofformation,entitytype,agentfirstname,agentmiddlename,agentlastname,agentsuffix,agentorganizationname,agentprincipaladdress1,agentprincipaladdress2,agentprincipalcity,agentprincipalstate,agentprincipalzipcode,agentprincipalcountry,agentmailingaddress1,agentmailingaddress2,agentmailingcity,agentmailingstate,agentmailingzipcode,agentmailingcountry,entityformdate`
- **Dates:** `MM/DD/YYYY`.
- **Statuses:**

  | Status | Rows |
  | --- | --- |
  | Delinquent | 1,151,596 |
  | Good Standing | 1,032,449 |
  | Voluntarily Dissolved | 600,854 |
  | Administratively Dissolved | 157,832 |
  | Withdrawn | 80,525 |
  | Noncompliant | 32,428 |
  | Revoked | 20,687 |
  | Judicially Dissolved | 15,926 |
  | Exists | 15,659 |
  | Merged | 10,164 |
  | Converted | 4,838 |
  | Registered Agent Resigned | 663 |
  | Effectiveness Prevented | 228 |
  | Dissolved (Term Expired) | 144 |
  | Consolidated | 18 |
- **Entity types** include `DLLC`, `DPC`, `DNC`, `FLLC` and `FPC`. Entities older than 1987 were renumbered with a `1987…` prefix. Only agents are listed, no officers.
- **Sentinel:** `19871009071`, THE MANITOU AND PIKE'S PEAK RAILWAY COMPANY, 1888-11-17, Good Standing.

### 10.6 Iowa (spec 12)

- **Moved off Socrata:** data.iowa.gov has left Socrata, and the old id `ez5t-3qay` returns 404.
- **Download:** the dataset page is https://data.iowa.gov/catalog/dataset/554. The download URL `https://data.iowa.gov/api/dataset-download?path=datasets%2F554%2Frows.csv` comes from the portal's download button (`getDownloadUrl`) and is undocumented.
- **Format:** the download is a zip holding one CSV, `active_iowa_business_entities_554_rows.csv`. It sends neither `ETag` nor `Last-Modified`. Streaming it through `funzip` failed with "zipfile ended prematurely"; unzip a saved copy instead.
- **Header:**

  `corp_number,legal_name,corporation_type,effective_date,registered_agent,ra_address_1,ra_address_2,ra_city,ra_state,ra_zip,ra_latitude,ra_longitude,ra_location,home_office,ho_address_1,ho_address_2,ho_city,ho_state,ho_zip,ho_country,ho_latitude,ho_longitude,ho_location`
- **Contents:** active entities only. `effective_date` is `YYYY-MM-DD`, and `corp_number` has leading zeros. The page reports 348,270 rows (read on the page, not counted), updated monthly, last on 2026-10-08. CC BY 4.0.
- **Sentinel:** `019862`, HY-VEE, INC., 1938-01-03, verified in the streamed file. There is no row-level API.

### 10.7 Connecticut (spec 11)

- **Business Master:** data.ct.gov `n7gp-d28j`, 1,303,035 rows, all statuses, updated daily. Public Domain. HEAD returns `ETag` and `Last-Modified`. The header as served ends with a space after `Geo_Location`:

  `Id,Name,Business_Type,Status,Sub_status,AccountNumber,Annual_Report_Due_Date,Began_Transacting_in_CT,Business_Street,Business_Unit,Business_City,Business_Country,Business_ZIP,Business_State,Business_Email_Address,Business_Name_in_state_country,Citizenship,Country_Formation,Date_Registration,Formation_Place,State_or_Territory_Formation,Date_of_Organization_Meeting,Dissolution_date,Mail_Jurisdiction_International_address,Mailing_Address,Mailing_International_Address,Mailing_Jurisdiction_Address,Mailing_Jurisdiction_BusinessStreet,Mailing_Jurisdiction_BusinessUnit,Mailing_Jurisdiction_BusinessCity,Mailing_Jurisdiction_BusinessState,Mailing_Jurisdiction_BusinessZipCode,Mailing_Jurisdiction_Country,Woman_Owned_Organization,Veteran_Owned_Organization,Minority_Owned_Organization,Org_Owned_by_Person_s_with_disabilities,Organization_is_LGBTQI_Owned,Category_Survey_Email_Address,NAICS_Code,NAICS_Sub_Code,Office_Jurisdiction_Address,Office_Jurisdiction_BusinessStreet,Office_Jurisdiction_BusinessUnit,Office_Jurisdiction_BusinessCity,Office_Jurisdiction_BusinessState,Office_Jurisdiction_BusinessZipCode,Office_in_Jurisdiction_Country,Reason_for_Administrative_Dissolution,Record_Address,Records_Address_Street,Records_Address_Unit,Records_Address_City,Records_Address_State,Records_Address_Zip_Code,Records_Address_Country,Total_Authorized_Shares,CREATE_DT,Geo_Location `
- **`Status`:** Active 464,565, plus Forfeited, Dissolved, Revoked, Withdrawn, Merged, Expired Reservation, Rejected and others.
- **`Date_Registration`:** `MM/DD/YYYY`. Reservations carry the placeholder `01/03/0001`.
- **`NAICS_Code`:** text such as `Hardware Manufacturing (332510)`, often empty.
- **Principals:** `ka36-64k6`, 1,796,710 rows. `Unique_Key` is the business `Id`; `Designation` is Officer, Director and so on. Header:

  `Unique_Key,Principal Name,First Name,Middle Name,Last Name,Suffix,Designation,Business Street Address 1,Business Street Address 2,Business Street Address 3,Business City,Business State,Business Zip Code,Business Country,Business International Address,Residence Address,Residence Street Address 1,Residence Street Address 2,Residence Street Address 3,Residence City,Residence State,Residence Zip Code,Residence Country,Residence International Address,Type,CREATE_DT`
- **Agents:** `qh2m-n44y`, 1,319,919 rows. How it links to Business Master is unclear: `business_id` returned nothing for the sentinel.
- **Sentinel:** `Id` 001t000000WmVHCAA3, `AccountNumber` 0074441, STANLEY BLACK & DECKER, INC., 1901-06-04, Active, ZIP 06053.

### 10.8 Oregon (spec 11)

- **Dataset:** data.oregon.gov `tckn-sxa6`, "Active Businesses - ALL". Export: `https://data.oregon.gov/api/views/tckn-sxa6/rows.csv?accessType=DOWNLOAD`. Weekly per the metadata; data refreshed 2026-10-13. HEAD returns `ETag` and `Last-Modified` with `Content-Length: 0`. No licence is stated.
- **Rows:** 1,582,772 rows covering 567,506 active entities. Each entity has one row per associated name type: `PRINCIPAL PLACE OF BUSINESS`, `MAILING ADDRESS`, `REGISTERED AGENT`, `AUTHORIZED REPRESENTATIVE`.
- **Header:**

  `Registry Number,Business Name,Entity Type,Registry Date,Associated Name Type,First Name,Middle Name,Last Name,Suffix,Not of Record Entity,Entity of Record Reg Number,Entity of Record Name,Address,Address Continued,City,State,Zip,Jurisdiction,Business Details`
- **Format:** `Registry Date` is `MM/DD/YYYY hh:mm:ss AM`. There is no EIN and no NAICS.
- **Sentinel:** `1333616`, PENDLETON WOOLEN MILLS, INC., 1909-02-16, ZIP 97209.

### 10.9 District of Columbia (spec 11)

- **Download:** `https://opendata.dc.gov/api/download/v1/items/5238c4fd99c843a1bd7679a243747a8c/csv?layers=0`. It answers 302 to `https://hub.arcgis.com/api/v3/datasets/5238c4fd99c843a1bd7679a243747a8c_0/downloads/data?format=csv&spatialRefId=3857&where=1%3D1`, which returns `Last-Modified: Fri, 16 Oct 2026 13:21:23 GMT` and a weak `ETag: W/"2f2c262be597c1f4870113b9880bd633-7"`. CC BY 4.0, daily.
- **Rows:** 505,487, all statuses.

  | Status | Rows |
  | --- | --- |
  | Revoked | 313,807 |
  | Active - In Good Standing | 118,037 |
  | Dissolved | 32,568 |
  | Withdrawn | 30,828 |
  | Merged | 5,563 |
  | Inactive - Cancelled | 2,783 |
  | Terminated | 741 |
  | Domesticated | 630 |
  | Active - Not in Good Standing | 304 |
  | Converted | 114 |
  | Consolidated | 112 |
- **Header,** after a UTF-8 BOM. The `BUSNIESS` misspellings are as served:

  `FILE_NUMBER,ENTITY_STATUS,LOCALE,MODELTYPE,BUSINESS_NAME,BUSNIESS_ADDRESS_LINE1,BUSNIESS_ADDRESS_LINE2,BUSNIESS_ADDRESS_LINE3,BUSNIESS_ADDRESS_LINE4,BUSINESS_CITY,BUSINESS_STATE,ZIPCODE,BUSINESS_COUNTRY,SUFFIX,RA_NAME,RA_ADDRESS1,RA_ADDRESS2,RA_ADDRESS3,RA_ADDRESS4,RA_CITY,RA_STATE,RA_ZIPCODE,EFFECTIVE_DATE,FOREIGN_DATEOF_ORGANIZATION,NEXT_REPORTYEAR_DUE,DCS_LAST_MOD_DTTM,DATE_LAST_REPORT_FILED,NEXT_REPORTYEAR,LATESTFILED_REPORTDATE,LATESTREPORT_YEARFILED,OBJECTID,GLOBALID`
- **Format:** `EFFECTIVE_DATE` is `YYYY/MM/DD HH:MM:SS+00`.
- **Row API:** `https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Business_Licensing_and_Grants_WebMercator/FeatureServer/0/query`.
- **Sentinels:**
  - `540000`, GEORGETOWN UNIVERSITY (THE), 1844-06-10.
  - `571294`, WASHINGTON GAS LIGHT Company, 1957-03-25. That is a re-registration date; the company dates to 1848.

## 11. States out of scope, and why

Each state below still gets every national source: PPP, Form 5500 2009 to 2025, SBA 7(a) and 504, SAM.gov and FMCSA. Only its own registry is missing, and with it formation dates, statuses and officers for businesses with no other evidence. Prices and access come from the official page where it opened, otherwise from search results; such lines say "page" or "search".

| State | PPP loans | Reason | What would unblock it |
| --- | --- | --- | --- |
| CA | 1,270,593 | Bulk data needs a logged-in bizfile Online account. A full "BE Bulk Order Master Unload" costs $100; weekly data is free once logged in (bizfile manual PDF, read by request). | The owner creates an account and downloads an unload into `include/data/raw/ca/`; then one state module. |
| IL | 620,021 | ilsos.gov corporate-data pages return 403 to scripts. A fixed 160-character master file exists; price and access are unconfirmed. The public search forbids bulk use. | The owner requests the file. |
| GA | 553,311 | Paid: $1,000 one-time, or $100 setup plus $500 a month, with a signed agreement (georgia.gov/bulk-corporations-data, page). | Purchase. |
| OH | 351,984 | ohiosos.gov returns 403 (Cloudflare) to scripts. Free monthly reports cover new filings only, not the registry (search). | The owner downloads by hand. New filings alone would not date old businesses. |
| NJ | 302,430 | No official bulk file found. One third-party claim of $0.0185 per record is unverified. | None known. |
| MI | 291,529 | No official bulk file found. | None known. |
| NC | 258,993 | Paid: $750 setup plus $2,000 per fiscal year (data subscription manual, March 2024). The search forbids automated use. | Purchase. |
| MO | 233,136 | No official bulk file found. | None known. |
| TN | 229,734 | Paid portal at tncab.tnsos.gov; price not found. | Purchase. |
| MN | 225,357 | Free for non-commercial use only, with a registered account and a certified request form that forbids republishing. Commercial use needs a licence and fee; the active list is $30 (page). | The owner's licence decision. |
| LA | 217,315 | No official bulk file found. | None known. |
| MA | 217,222 | No official bulk file found. | None known. |
| WA | 195,227 | The SOS "AllData" extract was retired; `apps.sos.wa.gov/corps/AllData.aspx` returns 404 (verified). | None known. |
| MD | 190,721 | Paid: SpecPrint, $0.04 per account, $40 minimum (page). | Purchase. |
| WI | 187,821 | Paid: $40 per file through form CORP51 (search). | Purchase. |
| IN | 186,166 | Paid: from $35 a month for new filings to $9,500 a year (regulatory PDF). INBiz bulk pages return 403. | Purchase. |
| AL | 169,555 | No official bulk file found. | None known. |
| AZ | 169,242 | No official bulk file found. | None known. |
| OK | 154,905 | No free bulk file found; vendors only. | None known. |
| SC | 150,226 | No official bulk page found. | None known. |
| MS | 138,394 | No free bulk file found; vendors only. | None known. |
| KY | 128,431 | Paid Bulk Data Service with a subscriber agreement (page). | Purchase. |
| KS | 126,400 | No free bulk file found; vendors only. | None known. |
| NV | 118,223 | Paid: about $125 per full dump (third-party pages). SilverFlume was replaced by ORION. | Purchase. |
| NE | 114,183 | Paid: $15 per 1,000 records (page). | Purchase. |
| AR | 102,039 | Subscriber account through the Tyler bulk-data portal; fee not stated (page). | Purchase. |
| UT | 84,023 | No free bulk file found; vendors only. | None known. |
| PR | 70,201 | No official bulk file found. Open Knowledge rated it "not available in bulk" in 2015. | None known. |
| SD | 64,079 | Paid, through a vendor. | Purchase. |
| ID | 52,388 | No official bulk page found. | None known. |
| ND | 51,521 | No official bulk page found. | None known. |
| ME | 47,407 | Paid: $150 per list (search; the page returned 403). | Purchase. |
| MT | 47,066 | No official bulk page found. | None known. |
| HI | 44,564 | The Entity List Builder is paid. Honolulu's `9k54-ztb8` is labelled out of date since 2022-06-08 (verified). | Purchase. |
| NM | 41,167 | No free bulk file found; vendors only. | None known. |
| NH | 40,933 | No official bulk page found. | None known. |
| RI | 33,805 | Paid: $250 for the active corporate database (page). | Purchase. |
| WV | 33,317 | Monthly account holders only, at apps.wv.gov/SOS/BulkData (page, verified by request). | Purchase. |
| DE | 27,734 | No bulk file; paid per record. `data.delaware.gov/5zy2-grhr` holds revenue business licences without formation dates. | Purchase. |
| WY | 25,651 | Paid monthly subscription (official form PDF). | Purchase. |
| AK | 23,693 | Says a free database download exists, but commerce.alaska.gov answers 403 to scripts behind a DataDome bot check. Per the owner's standing rule, nothing tried to get around it. | The owner downloads in a browser. |
| VT | 21,697 | A free weekly full download needs a bizfilings.vermont.gov login (Secretary of State memo, 2025-04-29; MuckRock). | The owner creates an account. |
| GU, VI, MP, AS | 3,584; 3,403; 919; 314 | Territories, not researched. | Research. |

Free registries in scope, with PPP loans: TX 938,551, FL 983,321, NY 734,799, PA 342,420, VA 221,088, CO 192,267, IA 171,716, CT 117,888, OR 115,871 and DC 29,520. Together that is 3,847,441 of 11,468,210 loans (33.5%).

## 12. Sources considered and not included

| Source | Why not | Note |
| --- | --- | --- |
| IRS Exempt Organizations BMF (`irs.gov/pub/irs-soi/eo_<st>.csv`) | Nonprofits only | Could later flag nonprofit EINs among plan sponsors |
| NPPES NPI (CMS), `NPPES_Data_Dissemination_<Month>_<Year>_V2.zip`, 1,159,720,219 bytes | Healthcare organizations only. Enumeration dates start around 2005, so it cannot show 30 years | Has authorized-official names for medical practices; a candidate for a later spec |
| OpenCorporates bulk | An enterprise contract; free only for journalists, NGOs and academics (page) | |
| USAspending recipients | Repeats SAM data and has no start date | |
| FCC ULS business licences | The old download path now redirects to a search page | Not checked further |
| OSHA inspections | Bulk links moved to a portal that needs a key (page) | Not verified |
| FDA establishments, USPTO trademark first-use dates | Not checked | Trademark first-use dates are a possible age signal |
| New York "All Filings" and "Status History" (21M rows each) | Inactive New York entities, not needed while the registry is active-only | |
| Florida daily delta files and fictitious names | The quarterly full file is enough for now | |
| SBA 7(a) and 504 `BusinessAge` buckets | Too coarse to push a date back reliably | Carried as a column |

## Toolchain

- **Machine:** Ubuntu 26.04 arm64 (a VMware Fusion VM), 8 cores, 56 GB RAM, 153 GB free. Docker 29.1.3 with Compose 2.40; Docker is enabled at boot. Host user is uid 1000, gid 1000. `make` is not installed. mise and uv 0.13.0 are installed, and the mise registry maps `astro` to `github:astronomer/astro-cli`.
- **Astro CLI v1.46.0** ships `astro_1.46.0_linux_arm64.tar.gz`, which runs here. `astro dev init` writes `FROM astrocrpublic.azurecr.io/runtime:3.3-9`. The CLI waits on `/api/v2/monitor/health` and applies `docker-compose.override.yml`.
- **Astro Runtime image `3.3-9`:**
  - Manifests for `linux/amd64` and `linux/arm64`; 1.5 GB pulled.
  - Airflow `3.3.2+astro.2`, Python 3.14.8.
  - Runs as user `astro`, uid 50000, member of group 0.
  - `AIRFLOW_HOME=/usr/local/airflow` is `astro:root` with mode 0775. `PYTHONPATH=/usr/local/airflow`. `TZ=Etc/UCT`.
  - `requests` 2.34.2 is preinstalled. `duckdb` is not.
- **Compose template:** the CLI's Airflow 3 template runs postgres, db-migration, scheduler, dag-processor, api-server and triggerer. Every service except db-migration has `restart: unless-stopped`. `dags/`, `plugins/`, `include/` and `tests/` are bind-mounted into the Airflow services. Logs go to the `airflow_logs` volume.
- **Bind mount permissions:**
  - As the default uid 50000, writing a host directory owned by uid 1000 fails with `Permission denied`.
  - With `--user 1000:0`, the container can write the mount and `/usr/local/airflow/logs`, `airflow version` works, and DuckDB 1.5.6 writes Parquet with an atomic `os.replace`. `HOME` is `/` in that case, and nothing complained.
  - The resulting files are owned by uid 1000, gid 0, and the host user can delete them.
- **Airflow 3.3.2 CLI:**
  - `airflow dags trigger <dag_id> [-r RUN_ID] [-o json]`
  - `airflow dags list-runs <dag_id> [-o json] [--state ...]`
  - Both take the DAG id as a positional argument.
  - The trigger help says "If DAG is paused then dagrun state will remain queued, and the task won't run."
- **DuckDB 1.5.6** (cp314 wheels exist):
  - `jaro_winkler_similarity`, `try_strptime`, `regexp_extract`, macros, `SET VARIABLE` with `getvariable`, and `count(distinct x) over (...)` inside `qualify` all work.
  - `least` skips NULLs.
  - `date_sub('year', a, b)` counts complete years: 35 from 1990-12-31 to 2026-01-01, where `date_diff` gives 36.
  - `regexp_extract` returns `''`, not NULL, when there is no match.
  - Bound parameters work inside `COPY (...) TO`.
  - DuckDB cannot read a file with a `.part` suffix without an explicit `read_parquet`.
- **PyPI:** `apache-airflow` 3.3.2 requires Python `>=3.10,!=3.15`.

## Not verified

- A full download of either Texas export: throttling, total size and duration.
- Encoding validity and malformed rows across all 13 PPP files. Only the first rows were read.
- The real Texas PPP loan count. The estimate of 0.7 to 1.3 million is unconfirmed.
- Running the full Astro stack (`astro dev start`) with the `1000:0` override. Only single containers were tested. That is the skeleton's first verification step.
- Everything about the Google Places API.
- Phase 1b sources, as of 2026-10-17:
  - No full download of any new registry, SAM.gov, FMCSA, or the four later SBA files. Their sizes, durations, throttling and encodings are unknown until each spec's first run.
  - Florida's member list and encoding, and whether `curl --head` over SFTP reports size and modification time.
  - The SAM.gov field positions other than field 25. They come from GSA's published layout.
  - Iowa's row count (from its portal page) and Virginia's limited-partnership file.
  - Every price listed in section 11 that is marked "search".
  - Whether DuckDB's `excel` extension installs in the container.
