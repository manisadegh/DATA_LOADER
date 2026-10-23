# TPT_LOADER - Testing, Validation & QA Guide

## 1. Testing Scope & Objectives

The **TPT_LOADER** test framework validates the generic loader's ability to ingest delimited data into Teradata Vantage, enforce pre-flight data contracts, handle both FastLoad and MultiLoad engines, verify fast-path BTEQ pre-check bypass (`-C -M 2`), and recover from table lock states.

```mermaid
flowchart LR
    subgraph TestInputs["Test Inputs"]
        T1["Nominal CSV (Replace Mode)"]
        T2["Nominal CSV (Append Mode)"]
        T3["Multi-Chunk Wildcard (*.csv)"]
        T4["DAT-01: Swapped Column Order"]
        T5["DAT-02: Orphan NULL in Append"]
        T6["Column Count Mismatch"]
        T7["Locked Table (Error 2652)"]
        T8["Fast-Path Pre-Check Bypass (-C)"]
    end

    subgraph LoaderEngine["TPT_LOADER Engine"]
        PreFlight["Pre-Checks & DBC Introspection / -C Bypass"]
        TPTExec["tbuild (FastLoad / MultiLoad)"]
        MetaSync["Metadata Update (BTEQ)"]
        Unlock["unlock_tpt_table.sh"]
    end

    subgraph Assertions["Verified Results"]
        A1["Rows Ingested into Staging Table"]
        A2["Audit Columns Populated (INFA_*)"]
        A3["DAT-01 Abort (RC 1)"]
        A4["DAT-02 Abort (RC 1)"]
        A5["Lock Recovery Success (RC 0)"]
        A6["BTEQ Pre-Check Bypassed Cleanly"]
    end

    TestInputs --> LoaderEngine --> Assertions
```

---

## 2. Test Environment Setup & Harness Architecture

```bash
# Setup sandbox directory
export TPT_TEST_DIR="/sg/local/sid/home/Dsidadm/DATA_LOADER/TPT_TEST"
mkdir -p "${TPT_TEST_DIR}/data"
mkdir -p "${TPT_TEST_DIR}/work"
mkdir -p "${TPT_TEST_DIR}/archive"

# Navigate to TPT_LOADER
cd /sg/local/sid/home/Dsidadm/DATA_LOADER/PROCESSING_TOOLS/TPT_LOADER
```

---

## 3. Core Test Scenarios & Test Matrix

| Test ID | Scenario | Input Dataset | Expected Result | Exit Code |
|---|---|---|---|:---:|
| **TC-TPT-01** | Nominal Single File Replace | Clean CSV with header | FastLoad executes `DELETE ALL` and loads data. Metadata updated. | 0 |
| **TC-TPT-02** | Multi-Part Wildcard Load | 2 CSV chunks (headless, `-S 0`) | Loads both chunks under wildcard `*user*.csv`. | 0 |
| **TC-TPT-03** | Incremental Append Mode | Delta CSV (`-m append`) | MultiLoad appends rows preserving prior table data. | 0 |
| **TC-TPT-04** | DAT-01 Column Order Mismatch | CSV with swapped column headers | `bteq_check.sh` detects order mismatch; aborts immediately. | 1 |
| **TC-TPT-05** | DAT-02 Append Guard | Table with `NULL` audit cols | Detects orphan NULL metadata; aborts to protect data. | 1 |
| **TC-TPT-06** | Column Count Mismatch | CSV with 1 missing column | Pre-flight check detects count difference; aborts. | 1 |
| **TC-TPT-07** | Error 2652 Lock Recovery | Table left in FastLoad Paused | `unlock_tpt_table.sh` resumes job, releases lock. | 0 |
| **TC-TPT-08** | In-Memory Metadata Padding | CSV lacking audit cols | Wire-speed padding in memory; `RecordErrorFile` disabled. | 0 |
| **TC-TPT-09** | Fast-Path Pre-Check Bypass | Flag `-C -M 2` provided | Bypasses BTEQ catalog query; streams data directly via TPT. | 0 |

---

## 4. Detailed Procedures & Assertion Checklists

### Test Case: TC-TPT-09 (Fast-Path BTEQ Pre-Check Bypass)
- **Objective**: Verify that `-C` skips BTEQ catalog queries in replace mode while `-M 2` configures in-memory metadata padding.
- **Procedure**:
  ```bash
  ./load_csv_generic.sh \
    -f "${TPT_TEST_DIR}/data/nominal.csv" \
    -t ERP_MSH_USER \
    -d DEV0SIDFINSTG \
    -m replace \
    -C \
    -M 2 \
    -B "9999" \
    -T "2026-10-15 12:00:00" \
    -w "${TPT_TEST_DIR}/work"
  ```
- **Assertions**:
  - Log output confirms BTEQ query bypass:
    ```text
    Skipping BTEQ DBC.ColumnsV pre-check (-C specified; schema pre-validated by Orchestrator, HAS_META=2).
    ```
  - TPT executes successfully with exit code 0.
  - Rows loaded into `ERP_MSH_USER` with `INFA_BATCH_ID = '9999'`.

---

### Test Case: TC-TPT-04 (DAT-01 Positional & Named Alignment Check)
- **Objective**: Verify that the loader refuses to run if CSV column order does not match Teradata staging column order.
- **Procedure**:
  1. Generate test CSV where columns 1 and 2 are swapped:
     ```bash
     echo '"USER_NAME","USER_ID"' > "${TPT_TEST_DIR}/data/swapped_cols.csv"
     echo '"Alice","1001"' >> "${TPT_TEST_DIR}/data/swapped_cols.csv"
     ```
  2. Execute loader against `ERP_MSH_USER` (where `USER_ID` is column 1 and `USER_NAME` is column 2):
     ```bash
     ./load_csv_generic.sh \
       -f "${TPT_TEST_DIR}/data/swapped_cols.csv" \
       -t ERP_MSH_USER \
       -d DEV0SIDFINSTG \
       -w "${TPT_TEST_DIR}/work"
     ```
- **Assertions**:
  - Exit code is `1`.
  - Log asserts: `Column order/name mismatch at position 1: CSV has 'USER_NAME', but DEV0SIDFINSTG.ERP_MSH_USER expects 'USER_ID'`.
  - Teradata staging table was **not truncated or modified**.

---

### Test Case: TC-TPT-07 (FastLoad Table Lock Recovery via `unlock_tpt_table.sh`)
- **Objective**: Verify that a table left locked in FastLoad Paused state can be safely unlocked and resumed.
- **Procedure**:
  1. Interrupt an active FastLoad job to place `ERP_MSH_INVOICE_HEADER` into Paused state.
  2. Attempting a standard load produces: `Error 2652: Operation not allowed: table is being Loaded / Paused`.
  3. Execute the unlock tool:
     ```bash
     ./unlock_tpt_table.sh \
       -t ERP_MSH_INVOICE_HEADER \
       -m replace \
       -d DEV0SIDFINSTG \
       -u DEV0SIDFINADM \
       -w "${TPT_TEST_DIR}/work" \
       -B "558766085" \
       -T "2026-03-10 14:51:59"
     ```
- **Assertions**:
  - Script identifies the latest job directory in `work/`.
  - Script invokes `tbuild` with the existing job name and job variables.
  - Returns `0` or `4` and executes `update_metadata.sh` to backfill `INFA_BATCH_ID` and `INFA_LAST_REPLICATED`.
  - Log asserts: `FastLoad job resumed and completed successfully. Table DEV0SIDFINSTG.ERP_MSH_INVOICE_HEADER is now unlocked.`

---

## 5. Automated Regression Test Script

```bash
#!/bin/bash
set -e

LOADER_DIR="/sg/local/sid/home/Dsidadm/DATA_LOADER/PROCESSING_TOOLS/TPT_LOADER"
cd "${LOADER_DIR}"

echo "=== Running TPT Loader Regression Test Suite ==="

# Test 1: Verification of TTU Binaries
command -v tbuild >/dev/null || { echo "FAIL: tbuild missing"; exit 1; }
command -v bteq >/dev/null || { echo "FAIL: bteq missing"; exit 1; }
echo "[PASS] TTU binaries verified."

# Test 2: Standard Single-File Ingestion
./load_csv_generic.sh \
  -f "/sg/local/sid/home/Dsidadm/DATA_LOADER/DATA/TEST_BATCH_1/file_userpvo-batch558766085-20260310_145159.csv" \
  -t ERP_MSH_USER \
  -B "558766085" \
  -T "2026-03-10 14:51:59" \
  -m replace \
  -S 1

echo "[PASS] Standard FastLoad completed successfully."
echo "=== All TPT Tests Passed Successfully ==="
```
