# DATA_LOADER - Enterprise ELT Ingestion Suite for Teradata Vantage

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Platform: Linux / POSIX](https://img.shields.io/badge/platform-Linux%20%7C%20POSIX-lightgrey.svg)](https://www.kernel.org/)
[![Database: Teradata Vantage](https://img.shields.io/badge/database-Teradata%20Vantage%2016.20+-orange.svg)](https://www.teradata.com/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-red.svg)](#)

An enterprise-grade, high-throughput flat-file ELT ingestion framework feeding **Teradata Vantage** from upstream source extracts (primarily **Oracle Fusion Cloud BICC**).

Deployed in Unix as `/sg/local/sid/home/Dsidadm/DATA_LOADER`.

---

## 3-Tier Processing Hierarchy

```mermaid
flowchart TD
    subgraph TIER1["1. BICC_INTAKE_CONTROLLER (feeder.py) - Pure Intake Producer"]
        F1["Drop Zone Scanner & Multi-Batch Discovery"]
        F2["FIFO Chronological Queue Sentry (Oldest First)"]
        F3["File Stability Sentry (>0 bytes, Settling Window)"]
        F4["Zero Teradata Dependency (Pure In-Memory Header Inspection)"]
        F5["Manifest Factory (MD5, batch_descriptor.json, Raw Vaulting)"]
        F6["Atomic Batch Capsule Staging (LANDING_ZONE/<SRC>/BATCH_<TS>_<ID>/)"]
        F7["Supports --enqueue-only OR FAIL_STOP Subprocess Delegation"]
    end

    subgraph TIER2["2. DATA_INGESTION_ORCHESTRATOR (orchestrator.py) - Multi-Batch Consumer"]
        O1["Consumes 1..N Queued Batch Capsules in Strict FIFO Order"]
        O2["Fast-Path O(1) Batch Descriptor File Size Verification"]
        O3["Private Processing SAS (LOADING_ZONE/<SRC>/)"]
        O4["ZIP/GZ Archive Decompression & Solution A Multi-Chunk Normalization"]
        O5["Just-In-Time (JIT) Schema Guard & Auto-DDL (NOPI VARCHAR 4000)"]
        O6["Teradata State Tracking (BATCH_RUNS & BATCH_TASKS, Permanent PID)"]
        O7["ThreadPoolExecutor Parallel Entity Dispatch (-C -M 2 Fast-Path)"]
        O8["Completeness Barrier (100% Success -> Source-Keyed Post-Tasks -> ARCHIVE)"]
    end

    subgraph TIER3["3. TPT_LOADER (load_csv_generic.sh)"]
        T1["Fast-Path BTEQ Pre-Check Bypass (-C -M 2) when Pre-Synchronized"]
        T2["DBC.ColumnsV Pre-Flight (DAT-01 Alignment & DAT-02 Append)"]
        T3["Dynamic Schema Synthesis (FROM TABLE DELIMITED)"]
        T4["In-Memory Audit Padding (AcceptMissingColumns='Y')"]
        T5["Dual Engines: FastLoad (replace) / MultiLoad (append)"]
        T6["In-Database Audit Backfill (INFA_BATCH_ID / TIMESTAMP)"]
        T7["Table Lock Recovery (unlock_tpt_table.sh / Error 2652)"]
    end

    TIER1 -->|Stages Batch Capsules in LANDING_ZONE| TIER2
    TIER2 -->|Invokes load_csv_generic.sh (-C -M 2)| TIER3
    TIER3 -->|Wire-Speed Staging| Teradata[("${TDENV}SIDFINSTG Staging Tables")]
```

---

## Storage Architecture & Directory Layout

```
DATA_LOADER/
├── CONFIG/
│   └── entity_mapping.csv        # Centralized routing: signatures to staging tables
├── DATA/
│   ├── DROP_ZONE/<SOURCE>/       # Upstream arrival zone (strictly partitioned by source)
│   ├── LANDING_ZONE/<SOURCE>/    # Multi-batch FIFO queue (BATCH_<CLEAN_TS>_<BATCH_ID>/)
│   │   └── BATCH_<TS>_<ID>/      # Self-contained queued Batch Capsule
│   │       ├── *.csv / *.zip     # Payload data files
│   │       ├── MANIFEST_*.MF     # Standardized manifest
│   │       ├── batch_descriptor.json # Pre-computed metadata & column headers
│   │       └── RAW/              # Raw BICC manifest + RECEIPT_<SOURCE>_<TS>_<ID>.json
│   ├── LOADING_ZONE/<SOURCE>/    # Private processing SAS (active batch unpacked for TPT)
│   └── ARCHIVE_ZONE/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/ # Consolidated Batch Capsules
│       ├── *.csv / *.zip         # Loaded payload data files
│       ├── MANIFEST_*.MF         # Standardized manifest
│       ├── batch_descriptor.json # Batch metadata
│       └── RAW/                  # Raw BICC manifest + RECEIPT_<SOURCE>_<TS>_<ID>.json
├── DOCS/                         # Master Documentation Suite (18 guides + central index)
├── LOGS/
│   └── <SOURCE>/                 # Partitioned by source
│       ├── LOG_FEEDER_<SOURCE>_<EXEC_TS>.log # Feeder supervisor log
│       └── <YYYY-MM>/BATCH_<ID>_<TS>/        # Batch Log Capsule
│           ├── LOG_ORCHESTRATOR_<SOURCE>_<EXTRACT_TS>_<BATCH_ID>_<EXEC_TS>.log
│           └── TPT/              # TPT job variables, tbuild outputs, logs (TPT_<TARGET>_<RUN_TS>)
├── PROCESSING_TOOLS/
│   ├── COMMON/dataloader_core/   # Shared Core Python SDK (locking, db pool, schema reader, intake)
│   ├── BICC_INTAKE_CONTROLLER/   # Tier 1 Feeder (Pure Producer, FIFO, Manifest Factory)
│   ├── DATA_INGESTION_ORCHESTRATOR/ # Tier 2 Orchestrator (Multi-Batch Consumer, JIT Schema Guard)
│   └── TPT_LOADER/               # Tier 3 Ingestion Engine (FastLoad/MultiLoad, -C -M 2 bypass)
└── TESTS/                        # Automated Unix Test Suite (11 scenarios, 100% PASS)
    ├── scenarios/                # 01 to 11 automated bash test scenarios
    ├── DATASETS/                 # Immutable test batches (9001 to 9009)
    ├── unit/                     # Core SDK unit tests (unittest discover)
    ├── verify_database_and_storage.py # Deep Teradata & storage auditor
    └── OUTPUTS/                  # Archived run artifacts & all_test_outputs_latest.tar.gz
```

---

## 📚 Central Documentation Suite

A complete 18-document suite is available in [`DOCS/README.md`](DOCS/README.md) and synchronized with the team's Obsidian Vault:

| Category | Component | Available Guides |
|---|---|---|
| **Core SDK** | **dataloader_core** | [Technical Reference](DOCS/00_COMMON_CORE_SDK/01_dataloader_core_technical_reference.md) • [Onboarding Guide](DOCS/00_COMMON_CORE_SDK/02_onboarding_new_data_sources_guide.md) |
| **Tier 1** | **BICC_INTAKE_CONTROLLER** | [User Guide](DOCS/01_BICC_INTAKE_CONTROLLER/01_user_how_to_guide.md) • [Functional Spec](DOCS/01_BICC_INTAKE_CONTROLLER/02_functional_specification.md) • [Tech Manual](DOCS/01_BICC_INTAKE_CONTROLLER/03_technical_manual_and_inventory.md) • [QA Guide](DOCS/01_BICC_INTAKE_CONTROLLER/04_testing_and_qa_guide.md) |
| **Tier 2** | **DATA_INGESTION_ORCHESTRATOR** | [User Guide](DOCS/02_DATA_INGESTION_ORCHESTRATOR/01_user_how_to_guide.md) • [Functional Spec](DOCS/02_DATA_INGESTION_ORCHESTRATOR/02_functional_specification.md) • [Tech Manual](DOCS/02_DATA_INGESTION_ORCHESTRATOR/03_technical_manual_and_inventory.md) • [QA Guide](DOCS/02_DATA_INGESTION_ORCHESTRATOR/04_testing_and_qa_guide.md) |
| **Tier 3** | **TPT_LOADER** | [User Guide](DOCS/03_TPT_LOADER/01_user_how_to_guide.md) • [Functional Spec](DOCS/03_TPT_LOADER/02_functional_specification.md) • [Tech Manual](DOCS/03_TPT_LOADER/03_technical_manual_and_inventory.md) • [QA Guide](DOCS/03_TPT_LOADER/04_testing_and_qa_guide.md) |
| **System** | **DATA_LOADER Global** | [Architecture Spec](DOCS/04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/01_enterprise_architecture_specification.md) • [Deployment Guide](DOCS/04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/02_deployment_and_installation_guide.md) • [Operations Playbook & FAQ](DOCS/04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/03_production_operations_playbook_and_faq.md) |
| **Tutorial** | **Intake Controller Development** | [Step-by-Step Developer Tutorial](DOCS/05_SOURCE_INTAKE_CONTROLLER_DEVELOPMENT_GUIDE/01_step_by_step_intake_controller_development_tutorial.md) • Pluggable architecture & custom intake guide |
| **Tests**  | **Test Suite (Unix)** | [Test Playbook](TESTS/README.md) • 11 automated scenarios with Teradata DB & Storage audit (100% PASS) |

---

## Quick Start & Execution

### 1. Automated Supervised Execution (Recommended)
```bash
cd PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER
python3 feeder.py --config config.json [--enqueue-only] [--skip-post-tasks] [--source <SOURCE>]
```

### 2. Standalone Multi-Batch Orchestrator Execution
```bash
cd PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR
python3 orchestrator.py --config config.json [--skip-post-tasks] [--source <SOURCE>] [--post-tasks-file <path>]
```

### 3. Automated Test Suite Execution (Unix / Teradata)
```bash
cd TESTS
./run_all_tests.sh                # Run all 11 scenarios sequentially
./run_all_tests.sh --scenario 11  # Run specific scenario (1..11)
```

### 4. Standalone TPT Execution
```bash
cd PROCESSING_TOOLS/TPT_LOADER
./load_csv_generic.sh -f /path/to/file.csv -t TARGET_TABLE -m replace -C -M 2
```
