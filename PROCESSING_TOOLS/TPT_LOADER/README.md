# Generic Teradata Parallel Transporter (TPT) Loader

[![Bash 4.0+](https://img.shields.io/badge/shell-Bash%204.0+-brightgreen.svg)](https://www.gnu.org/software/bash/)
[![Teradata Parallel Transporter](https://img.shields.io/badge/TTU-TPT%20%2F%20tbuild-orange.svg)](https://www.teradata.com/)
[![Platform: Linux / POSIX](https://img.shields.io/badge/platform-Linux%20%7C%20POSIX-lightgrey.svg)](https://www.kernel.org/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-red.svg)](#)

A high-performance, modular, and schema-agnostic flat-file ingestion engine for **Teradata Vantage**. 

`TPT_LOADER` ingests delimited text files (Oracle Fusion BICC extracts, general CSV/TSV data) into Teradata staging tables with zero hardcoded table DDLs, dynamic schema introspection via BTEQ, fast-path BTEQ pre-check bypass (`-C -M 2`), automated table unlocking, audit metadata injection, and dual ingestion modes (`FastLoad` and `MultiLoad`).

---

## 📚 Complete Documentation Suite

Comprehensive operational, technical, and testing manuals are available in the [`docs/`](docs/) directory:

- 📖 **[User How-To & CLI Reference](docs/01_user_how_to_guide.md)**: Command-line options, fast-path flags (`-C -M 2`), job variables reference, execution examples, and lock recovery commands.
- 📐 **[Functional Specification](docs/02_functional_specification.md)**: Dynamic schema derivation, FastLoad vs MultiLoad engines, fast-path BTEQ pre-check bypass, DAT-01/DAT-02 checks, and audit backfill.
- ⚙️ **[Technical Manual & Function Inventory](docs/03_technical_manual_and_inventory.md)**: Modular POSIX bash framework, TPT template structure, BTEQ queries, and exit code propagation.
- 🧪 **[Testing, Validation & QA Guide](docs/04_testing_and_qa_guide.md)**: Test matrices, pre-flight column misalignment tests, append safety tests, and automated regression harnesses.

---

## Table of Contents

- [Key Capabilities](#key-capabilities)
- [Architecture & Modular Structure](#architecture--modular-structure)
- [Directory Layout](#directory-layout)
- [Prerequisites & System Requirements](#prerequisites--system-requirements)
- [Authentication & Environment Configuration](#authentication--environment-configuration)
- [Command-Line Interface (`load_csv_generic.sh`)](#command-line-interface-load_csv_genericsh)
  - [Full CLI Options Reference](#full-cli-options-reference)
  - [Usage Examples](#usage-examples)
- [Ingestion Modes (`replace` vs `append`)](#ingestion-modes-replace-vs-append)
- [Automated Table Unlock Tool (`unlock_tpt_table.sh`)](#automated-table-unlock-tool-unlock_tpt_tablesh)
- [Audit Columns & Metadata Injection](#audit-columns--metadata-injection)
- [Exit Codes & Return Codes](#exit-codes--return-codes)
- [Integration with Schedulers & Orchestrators](#integration-with-schedulers--orchestrators)
- [Troubleshooting & Best Practices](#troubleshooting--best-practices)

---

## Key Capabilities

- **Zero-Hardcoding Dynamic Schemas**: Introspects the destination table directly from Teradata data dictionaries (`DBC.ColumnsV`) at runtime, dynamically mapping input fields to table attributes without maintaining static TPT scripts.
- **Fast-Path BTEQ Pre-Check Bypass (`-C -M 2`)**: When invoked by upstream orchestrators that pre-validate or auto-migrate schemas (such as `DATA_INGESTION_ORCHESTRATOR`), skips redundant catalog lookups in replace mode while maintaining safety checks in append mode.
- **Dual Load Engines**:
  - **`replace` Mode (FastLoad)**: Utilizes the TPT `Load` operator with maximum parallel throughput, preceding the load with a fast table truncation (`DELETE ALL`).
  - **`append` Mode (MultiLoad)**: Utilizes the TPT `Update` operator to append incremental batches into existing tables without truncating pre-existing data.
- **Multi-Part / Wildcard Ingestion**: Processes multiple split chunk files simultaneously using wildcard globbing (e.g., `-f '/data/extract_part*.csv'`), maximizing I/O performance via multiple reader instances.
- **Audit Lineage Columns**: Automatically injects ETL tracking metadata (`INFA_LAST_REPLICATED` timestamp and `INFA_BATCH_ID`) directly into the target table, extracted from parameters or parsed from filenames.
- **Pre-Flight Validation**: Verifies file accessibility, non-emptiness, target table presence, and column count alignment prior to engaging Teradata database sessions.
- **Built-In Lock Recovery**: Ships with `unlock_tpt_table.sh` to automatically recover tables stuck in FastLoad Paused or MultiLoad Paused states.

---

## Architecture & Modular Structure

The loader follows a modular UNIX architecture where `load_csv_generic.sh` acts as a facade controller that coordinates specialized scripts in `lib/`:

```text
load_csv_generic.sh
  │
  ├── 1. env_and_helpers.sh     --> Initializes environment, formatting & logger
  ├── 2. parse_args.sh          --> Parses and validates CLI parameters & flags (-C, -M)
  ├── 3. pre_checks.sh          --> Checks file presence, readability, and non-vacuity
  ├── 4. bteq_check.sh          --> Queries DBC metadata or bypasses (-C) & runs DAT-01/02
  ├── 5. generate_jobvars.sh    --> Synthesizes dynamic jobvariables.txt configuration
  ├── 6. run_tpt.sh             --> Invokes 'tbuild' engine against load_csv_generic.tpt
  ├── 7. update_metadata.sh     --> Validates audit columns (INFA_BATCH_ID / REPLICATED)
  └── 8. archive_files.sh       --> Moves ingested files to archive destination (optional)
```

---

## Directory Layout

```text
TPT_LOADER/
├── load_csv_generic.sh         # Main executable CLI wrapper for data loading
├── unlock_tpt_table.sh         # Dedicated recovery script for locked staging tables
├── jobvariables_template.txt   # Reference template for TPT job variable properties
├── config/
│   └── global.env              # Environment defaults (database names, user defaults)
├── lib/
│   ├── archive_files.sh        # Atomic move to archive directory on job success
│   ├── bteq_check.sh           # Database column introspection via BTEQ (-C bypass)
│   ├── env_and_helpers.sh      # Logging utilities, SQL sanitization, clean_column_name
│   ├── generate_jobvars.sh     # Dynamic synthesis of TPT job variables (TPT_<TARGET_TABLE>_<RUN_TS>)
│   ├── load_csv_generic.tpt    # Master generic TPT script definition
│   ├── parse_args.sh           # Command-line option parsing and input sanitizer
│   ├── pre_checks.sh           # File and filesystem integrity verifications
│   ├── run_tpt.sh              # TPT execution controller ('tbuild')
│   └── update_metadata.sh      # Audit column handler
└── README.md                   # Repository technical documentation
```

---

## Prerequisites & System Requirements

- **Operating System**: Linux (RedHat, CentOS, Rocky, Ubuntu, Debian) or POSIX shell runtime.
- **Teradata Tools and Utilities (TTU)**:
  - `tbuild` (Teradata Parallel Transporter Base & Stream/Load/Update operators).
  - `bteq` (Basic Teradata Query utility).
- **Shell**: GNU Bash 4.0+.
- **Standard Tools**: `awk`, `sed`, `grep`, `coreutils`.

---

## Authentication & Environment Configuration

The script adheres to standard enterprise Teradata authentication protocols:

### Environment Variables

| Variable | Required | Description | Example |
| :--- | :---: | :--- | :--- |
| `TDPID` | **Yes** | Teradata database hostname, IP, or COP alias. | `ms-env.teradata.com` |
| `TDENV` | No | Prefix for environment-specific users/databases. | `DEV0` or empty |
| `TD_PASSWORD` | Optional | Plaintext password (only for non-wallet dev environments). | `MySecretPassword!` |
| `TPT_WORK_DIR`| No | Work directory for generated files, logs, and bad rows. | `TPT_LOADER/tmp/tpt_work` |

### Production Authentication (Teradata Wallet)

In production environments, credentials should **never** be passed in plaintext. The loader natively resolves passwords through Teradata Wallet:
```bash
# In production, ensure TD_PASSWORD is unset:
unset TD_PASSWORD
# TPT and BTEQ will authenticate using $tdwallet(<user>)
```

---

## Command-Line Interface (`load_csv_generic.sh`)

### Full CLI Options Reference

```bash
load_csv_generic.sh -f <file|pattern> -t <table> [OPTIONS]
```

| Flag | Parameter | Mandatory | Default | Description |
| :---: | :--- | :---: | :--- | :--- |
| `-f` | `<file\|pattern>` | **Yes** | — | File path, or quoted wildcard pattern for multi-part files. |
| `-t` | `<table>` | **Yes** | — | Target staging table name (case-insensitive). |
| `-d` | `<database>` | No | `${TDENV}${DB_STG}` | Target Teradata database where table resides. |
| `-k` | `<utility_db>` | No | `${TDENV}${DB_WRK}` | Work database for TPT log, error (`_ET`, `_UV`), and work tables. |
| `-u` | `<user>` | No | `${TDENV}${SID_ADM_USER}` | Teradata logon username. |
| `-m` | `replace\|append` | No | `replace` | Ingestion mode: `replace` (FastLoad) or `append` (MultiLoad). |
| `-s` | `<delimiter>` | No | `,` | CSV field delimiter character. |
| `-S` | `<skip_rows>` | No | `1` | Number of header rows to skip in the source file (`0` for headless CSVs). |
| `-Y` | `<Y\|N>` | No | `N` | Skip header rows on every file when loading wildcards (`SkipRowsEveryFile`). |
| `-e` | `<error_limit>` | No | `1` | Number of rejected records before aborting the job. |
| `-r` | `<reader_instances>`| No | `1` | Parallel DataConnector reader instances. |
| `-l` | `<load_instances>` | No | `1` | Parallel Load / Update operator instances. |
| `-x` | `<max_sessions>` | No | `8` | Maximum concurrent database sessions allocated to the load. |
| `-B` | `<batch_id>` | No | *auto-extracted* | Explicit Batch ID string stored in `INFA_BATCH_ID`. |
| `-T` | `<timestamp>` | No | *auto-extracted* | Timestamp formatted `YYYY-MM-DD HH:MM:SS` for `INFA_LAST_REPLICATED`. |
| `-C` | None | No | `N` | Fast-path flag: skips BTEQ `DBC.ColumnsV` pre-check when pre-validated by Orchestrator. |
| `-M` | `<0\|2>` | No | `2` | Audit metadata columns count override when used with `-C`. |
| `-a` | `<archive_dir>` | No | *none* | Directory to move loaded files to on success. |
| `-w` | `<work_dir>` | No | `TPT_LOADER/tmp/tpt_work` | Local work directory for logs and generated files. |
| `-v` | `<jobvars_file>` | No | *none* | Custom jobvariables file to provide default values. |

---

### Usage Examples

#### 1. Fast-Path Load (Invoked by Orchestrator with `-C -M 2`)
```bash
./load_csv_generic.sh \
  -f "/data/loading/file_userpvo-batch1003-.csv" \
  -t "ERP_USER" \
  -d "DEV0SIDFINSTG" \
  -k "DEV0SIDFINWRK" \
  -u "DEV0SIDFINADM" \
  -m replace \
  -C \
  -M 2 \
  -B "1003" \
  -T "2026-10-15 12:00:11"
```

#### 2. Multi-Chunk Wildcard Load (High Performance)
Ingesting split files (`part1.csv`, `part2.csv`, ...) with 4 reader instances and `-S 0` (first chunk header stripped):
```bash
./load_csv_generic.sh \
  -f "/data/loading/file_poheadersextractpvo-batch1002-*.csv" \
  -t "ERP_PO_HEADERS" \
  -d "DEV0SIDFINSTG" \
  -k "DEV0SIDFINWRK" \
  -u "DEV0SIDFINADM" \
  -m replace \
  -C \
  -M 2 \
  -S 0 \
  -r 4 \
  -x 12 \
  -B "1002"
```

#### 3. Incremental Append Load (MultiLoad)
Appending delta records without truncating the existing table:
```bash
./load_csv_generic.sh \
  -f "/data/landing/delta_invoices_20261012.csv" \
  -t "ERP_AP_INVOICE_LINES" \
  -d "DEV0SIDFINSTG" \
  -k "DEV0SIDFINWRK" \
  -m append \
  -B "DELTA_20261012"
```

---

## Ingestion Modes (`replace` vs `append`)

| Feature | `replace` Mode | `append` Mode |
| :--- | :--- | :--- |
| **TPT Operator** | `Load` Operator (FastLoad protocol) | `Update` Operator (MultiLoad protocol) |
| **Pre-Load Action** | Issues `DELETE ALL FROM <target_table>` | None (preserves existing rows) |
| **Target Requirement** | Table must be empty before data insert | Table can be populated |
| **Throughput** | Maximum (block-level streaming) | High (row-level merge/insert) |
| **Lock Behavior** | Exclusive table lock during load | Read-permitted or write table lock |
| **Failure Recovery** | FastLoad Paused state -> Restart TPT | MultiLoad Paused state -> `RELEASE MLOAD` |

---

## Automated Table Unlock Tool (`unlock_tpt_table.sh`)

When a TPT job is abruptly killed (server restart, network drop, timeout), Teradata places the target table in a **Paused** state to preserve transactional integrity:
- **FastLoad Paused (Error 2652)**: Occurs when `replace` mode was interrupted.
- **MultiLoad Paused (Error 2574)**: Occurs when `append` mode was interrupted.

`unlock_tpt_table.sh` automatically clears these locks:

```bash
./unlock_tpt_table.sh -t <target_table> -d <target_db> -u <user> [-m replace|append]
```

### Options

| Flag | Parameter | Description |
| :---: | :--- | :--- |
| `-t` | `<table>` | Name of the locked table (mandatory). |
| `-d` | `<database>` | Database where the locked table resides. |
| `-u` | `<user>` | Logon user for Teradata. |
| `-m` | `replace` | Clears FastLoad lock by running a dummy/restart TPT pass and backfills metadata. |
| `-m` | `append` | Clears MultiLoad lock by executing `RELEASE MLOAD <table>;` via BTEQ. |

---

## Audit Columns & Metadata Injection

The loader natively populates two enterprise audit columns in the target table:

1. **`INFA_LAST_REPLICATED`**: `TIMESTAMP(0)` representing the extraction or load timestamp.
   - Extracted from `-T <timestamp>` or filename timestamps (`YYYYMMDD_HHMISS`).
2. **`INFA_BATCH_ID`**: `VARCHAR(100)` representing the batch identifier.
   - Extracted from `-B <batch_id>` or filename patterns (`-batch<id>-`).

> [!NOTE]
> When `-M 2` is supplied, `FILE_READER` sets `AcceptMissingColumns = 'Y'` and `RecordErrorFile = ""`. The Teradata DataConnector pads the audit columns with `NULL` in memory at wire speed, and `update_metadata.sh` executes the targeted SQL `UPDATE` post-load.

---

## Exit Codes & Return Codes

| Exit Code | Classification | Meaning | Recommended Action |
| :---: | :--- | :--- | :--- |
| **`0`** | **SUCCESS** | TPT completed successfully (`tbuild` exit code `0` or `4` warning). | Data loaded into table. |
| **`1`** | **USAGE / PRE-CHECK** | File not found, file empty, or column count mismatch. | Verify input file path, delimiter, and target table columns. |
| **`2`** | **DATABASE CONNECTION** | Target table not found, invalid credentials, or TDPID unreachable. | Check Teradata network access, logon, and target schema. |
| **`3`** | **TPT JOB FAILURE** | TPT execution aborted (`tbuild` exit code `8` or `12`). | Inspect `$TPT_WORK_DIR/<job>.log` for rejected rows and error tables. |

---

## Troubleshooting & Best Practices

1. **Table Lock Error 2652 / 2574**:
   - Run `unlock_tpt_table.sh -t <TABLE> -m <MODE>`.
   - Never drop staging tables manually while error tables (`_ET`, `_UV`) still exist.
2. **Column Count Mismatch (Exit Code 1)**:
   - Ensure the delimiter specified with `-s` matches the file (comma, tab, semicolon).
   - Verify if source CSV has an unexpected number of columns relative to the target table definition.
3. **Inspecting Rejection Tables**:
   - Error tables are stored in the utility database (`-k`, e.g. `DEV0SIDFINWRK`):
     - `<TABLE>_ET`: Acquisition errors (data conversion, invalid dates).
     - `<TABLE>_UV`: Application errors (uniqueness violations).
