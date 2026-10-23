# DATA_LOADER - Deployment, Environment & Installation Guide

## 1. Target Environment Overview & Topology

The **DATA_LOADER** framework is deployed across a multi-tier Unix enterprise architecture feeding **Teradata Vantage**:

```
Development (DEV)  -->  Integration (INT)  -->  Pre-Production (PPROD)  -->  Production (PROD)
   [DEV0 prefix]           [INT0 prefix]             [PPR0 prefix]             [PRD0 prefix]
```

### 1.1 Deployment Base Path
In all environments, the root deployment directory is hosted under the administrative service account `Dsidadm`:
```
/sg/local/sid/home/Dsidadm/DATA_LOADER
```

### 1.2 User Profile Exports (`~/.profile`)
The operating system environment is initialized via the shell profile:
```bash
# Teradata Environment Configuration
export TDENV="DEV0"            # Target database prefix (DEV0 / INT0 / PPR0 / PRD0)
export ENV="DEV"              # Logical tier
export USER_CHAPEAU="DEVADM"  # Top-level chapeau user
export TDPID="tdadev"         # Teradata system gateway COP
export SID_ADM_USER="SIDFINADM"# Administrative user suffix
export TDADEV="2"             # Environment ID
export LANG="C"               # POSIX byte sorting & encoding
```

### 1.3 Database Schema Conventions
The framework dynamically resolves target databases by prepending `${TDENV}`:
- **Staging Database**: `${TDENV}SIDFINSTG` (e.g. `DEV0SIDFINSTG`, `PRD0SIDFINSTG`)
- **Technical Database**: `${TDENV}SIDFINTCH` (hosts `BATCH_RUNS` and `BATCH_TASKS`)
- **Work/Utility Database**: `${TDENV}SIDFINWRK` (hosts TPT `LG_`, `ET_`, `UV_`, `WT_` tables)

---

## 2. Prerequisites & Software Dependencies

### 2.1 System Requirements
- **Operating System**: Red Hat Enterprise Linux (RHEL) 7, 8, or 9 / Rocky Linux / Oracle Linux.
- **Shell**: GNU Bash (`/bin/bash`) with POSIX pipefail support.
- **Python**: Python 3.8 or newer (with `teradatasql` driver installed).
- **Teradata TTU**: Teradata Tools and Utilities 16.20, 17.10, or 17.20 (`tbuild`, `bteq`, `tdwallet`).

### 2.2 Verifying Prerequisites via Discovery Script
The repository provides a diagnostic script [`collect_env_info.sh`](../../collect_env_info.sh) to automatically audit the host environment:
```bash
cd /sg/local/sid/home/Dsidadm/DATA_LOADER
./collect_env_info.sh
```

Alternatively, run manual checks as user `Dsidadm`:
```bash
# 1. Verify Shell
echo "$SHELL" | grep -q "bash" && echo "[OK] Bash shell verified"

# 2. Verify Python & teradatasql
python3 -c "import sys, teradatasql; print(f'[OK] Python {sys.version.split()[0]} and teradatasql {teradatasql.__version__} present')"

# 3. Verify TTU Binaries
for cmd in tbuild bteq tdwallet; do
    command -v "$cmd" >/dev/null && echo "[OK] $cmd found" || echo "[FAIL] $cmd missing"
done
```

---

## 3. Deployment Package Layout & Storage Tier Setup

### 3.1 Package Extraction & Deployment Base
Deploy the distribution package into the root path:
```bash
BASE_DIR="/sg/local/sid/home/Dsidadm/DATA_LOADER"
mkdir -p "${BASE_DIR}"
cd "${BASE_DIR}"

# Extract release archive (if installing from tarball)
# tar -xzf /path/to/DATA_LOADER_latest.tar.gz -C "${BASE_DIR}"
```

### 3.2 Storage Tier Initialization Script
Initialize the runtime storage directories, partitioned strictly by upstream source system:
```bash
BASE_DIR="/sg/local/sid/home/Dsidadm/DATA_LOADER"

# 1. Initialize root directories
mkdir -p "${BASE_DIR}/CONFIG"
mkdir -p "${BASE_DIR}/DATA"
mkdir -p "${BASE_DIR}/LOGS"

# 2. Initialize source-partitioned storage tiers
for SRC in "ORACLE_FUSION" "CRM"; do
    mkdir -p "${BASE_DIR}/DATA/DROP_ZONE/${SRC}"
    mkdir -p "${BASE_DIR}/DATA/LANDING_ZONE/${SRC}"
    mkdir -p "${BASE_DIR}/DATA/LOADING_ZONE/${SRC}"
    mkdir -p "${BASE_DIR}/DATA/QUARANTINE/${SRC}"
    mkdir -p "${BASE_DIR}/DATA/ARCHIVE_ZONE/${SRC}"
    mkdir -p "${BASE_DIR}/LOGS/${SRC}"
done

# 3. Enforce secure POSIX permissions (Dsidadm:dsidgrp, rwxr-x---)
chmod 750 "${BASE_DIR}"
chmod -R 750 "${BASE_DIR}/DATA" "${BASE_DIR}/LOGS" "${BASE_DIR}/CONFIG"
```

### 3.3 Complete Production Deployment Package Layout
```
/sg/local/sid/home/Dsidadm/DATA_LOADER/
├── CONFIG/
│   └── entity_mapping.csv           # Master source & entity routing configuration
├── DATA/
│   ├── DROP_ZONE/<SOURCE>/          # Upstream arrival zone (strictly partitioned by source)
│   ├── LANDING_ZONE/<SOURCE>/       # Multi-batch FIFO queue (BATCH_<CLEAN_TS>_<BATCH_ID>/)
│   ├── LOADING_ZONE/<SOURCE>/       # Private processing SAS (decompression, header stripping)
│   ├── QUARANTINE/<SOURCE>/         # Isolation quarantine for unmanifested / corrupted files
│   └── ARCHIVE_ZONE/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/ # Consolidated Batch Capsules
│       ├── *.csv / *.zip            # Loaded payload data files
│       ├── MANIFEST_*.MF            # Standardized manifest
│       ├── batch_descriptor.json    # Batch metadata
│       └── RAW/                     # Pristine raw manifest + RECEIPT_<SRC>_<TS>_<ID>.json
├── DOCS/                            # Comprehensive 16-guide documentation suite
├── LOGS/
│   └── <SOURCE>/                    # Partitioned by source
│       ├── LOG_FEEDER_<SOURCE>_<EXEC_TS>.log # Feeder supervisor log
│       └── <YYYY-MM>/BATCH_<ID>_<TS>/        # Batch Log Capsule
│           ├── LOG_ORCHESTRATOR_<SOURCE>_<EXTRACT_TS>_<BATCH_ID>_<EXEC_TS>.log
│           └── TPT/                 # TPT job variables, tbuild outputs, logs (TPT_<TARGET>_<RUN_TS>)
├── PROCESSING_TOOLS/
│   ├── COMMON/                      # Shared Core SDK (dataloader_core)
│   │   ├── dataloader_core/         # config, locking, db pool, mapping, manifest, checksum, capsule, schema_reader, logging
│   │   ├── docs/                    # Core SDK technical reference
│   │   └── README.md
│   ├── BICC_INTAKE_CONTROLLER/      # Tier 1 Feeder (Pure Producer, FIFO, Manifest Factory)
│   │   ├── feeder.py                # Feeder CLI entrypoint (<80 lines)
│   │   ├── config.json              # Active feeder configuration
│   │   ├── config_template.json     # Configuration template
│   │   ├── lib/                     # intake_service, scanner, manifest_factory, orchestrator_bridge
│   │   ├── docs/                    # Component documentation suite
│   │   └── README.md
│   ├── DATA_INGESTION_ORCHESTRATOR/ # Tier 2 Orchestrator (Multi-Batch Consumer, JIT Schema Guard)
│   │   ├── orchestrator.py          # Orchestrator CLI entrypoint (<80 lines)
│   │   ├── config.json              # Active orchestrator configuration
│   │   ├── config_template.json     # Configuration template
│   │   ├── ddl_technical_tables.sql # DDL for BATCH_RUNS & BATCH_TASKS
│   │   ├── lib/                     # orchestrator_service, schema_guard, sensor, db_state, tpt_worker, post_tasks, logger
│   │   ├── docs/                    # Component documentation suite
│   │   └── README.md
│   └── TPT_LOADER/                  # Tier 3 Ingestion Engine (FastLoad/MultiLoad, -C -M 2 bypass)
│       ├── load_csv_generic.sh      # Modular TPT loader entrypoint
│       ├── unlock_tpt_table.sh      # Automated table lock recovery tool
│       ├── config/global.env        # Environment defaults
│       ├── jobvariables_template.txt# TPT job variables template
│       ├── lib/                     # bteq_check, generate_jobvars, load_csv_generic.tpt, run_tpt
│       ├── docs/                    # Component documentation suite
│       └── README.md
├── TESTS/                           # Automated Unix Validation Test Suite (11 scenarios + 14 unit modules)
│   ├── run_all_tests.sh             # Master test runner
│   ├── run_all_tests.py             # Python test runner
│   ├── unit/                        # dataloader_core & service unit tests
│   ├── scenarios/                   # Scenarios 01 to 11
│   ├── DATASETS/                    # Pre-packaged test batches (BATCH_NOMINAL, etc.)
│   ├── verify_database_and_storage.py # Deep Teradata & storage auditor
│   ├── OUTPUTS/                     # Test run archives and consolidated tarball
│   └── README.md
└── collect_env_info.sh              # Environment discovery and validation diagnostic script
```

---

## 4. Step-by-Step Installation Procedure

### Step 1: Create Teradata Technical Tables (`${TDENV}SIDFINTCH`)
Execute the technical catalog DDL using `bteq` or run [`ddl_technical_tables.sql`](../../PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/ddl_technical_tables.sql):
```bash
bteq <<EOF
.logon ${TDPID}/${TDENV}${SID_ADM_USER},\$tdwallet(${TDENV}${SID_ADM_USER})

CREATE MULTISET TABLE ${TDENV}SIDFINTCH.BATCH_RUNS ,NO FALLBACK ,
     NO BEFORE JOURNAL, NO AFTER JOURNAL,
     CHECKSUM = DEFAULT, DEFAULT MERGEBLOCKRATIO
     (
        BATCH_ID VARCHAR(100) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        SOURCE VARCHAR(50) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        EXTRACT_TIMESTAMP VARCHAR(50) CHARACTER SET UNICODE NOT CASESPECIFIC,
        RUN_DATE DATE FORMAT 'YYYY-MM-DD',
        START_TIME TIMESTAMP(0),
        END_TIME TIMESTAMP(0),
        STATUS VARCHAR(20) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        PROCESS_PID INTEGER
     ) PRIMARY INDEX ( BATCH_ID ,SOURCE );

-- Migration statement for existing environments (add PROCESS_PID):
-- ALTER TABLE ${TDENV}SIDFINTCH.BATCH_RUNS ADD PROCESS_PID INTEGER;

CREATE MULTISET TABLE ${TDENV}SIDFINTCH.BATCH_TASKS ,NO FALLBACK ,
     NO BEFORE JOURNAL, NO AFTER JOURNAL,
     CHECKSUM = DEFAULT, DEFAULT MERGEBLOCKRATIO
     (
        BATCH_ID VARCHAR(100) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        SOURCE VARCHAR(50) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        EXTRACT_TIMESTAMP VARCHAR(50) CHARACTER SET UNICODE NOT CASESPECIFIC,
        ENTITY_NAME VARCHAR(100) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        FILE_NAME VARCHAR(500) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        STATUS VARCHAR(20) CHARACTER SET UNICODE NOT CASESPECIFIC NOT NULL,
        START_TIME TIMESTAMP(0),
        END_TIME TIMESTAMP(0),
        RETRY_COUNT INTEGER DEFAULT 0,
        ERROR_MESSAGE VARCHAR(1000) CHARACTER SET UNICODE NOT CASESPECIFIC
     ) PRIMARY INDEX ( BATCH_ID ,SOURCE );

.logoff
.quit
EOF
```

### Step 2: Configure Teradata Credentials
Store the database password securely in Teradata Wallet:
```bash
# Add credential to wallet
tdwallet add "${TDENV}${SID_ADM_USER}"
# Enter password securely when prompted
```

For python `teradatasql` connections using property files:
Ensure `~/.dbt/${TDENV}${SID_ADM_USER}_Key.properties` and `~/.dbt/${TDENV}${SID_ADM_USER}_Pass.properties` are populated and restricted to `chmod 600`.

### Step 3: Populate Entity Mapping (`CONFIG/entity_mapping.csv`)
Verify the master routing table exists in `CONFIG/entity_mapping.csv` (supports extended 9-column schema or legacy 5 columns):
```csv
SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION,DELIMITER,LOAD_MODE,SKIP_ROWS,HEADER_MODE
ORACLE_FUSION,ERP_MSH_INVOICE_HEADER,invoiceheaderextractpvo,".csv,.zip,.gz,.csv.gz",.csv,",",replace,1,first_chunk_only
ORACLE_FUSION,ERP_MSH_INVOICE_HEADER_AK,invoiceheaderextractpvo,".pecsv,.zip,.gz,.pecsv.gz",.pecsv,",",replace,1,first_chunk_only
ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv,.zip,.gz,.csv.gz",.csv,",",replace,1,first_chunk_only
ORACLE_FUSION,ERP_MSH_USER_AK,userpvo,".pecsv,.zip,.gz,.pecsv.gz",.pecsv,",",replace,1,first_chunk_only
CRM,CRM_MSH_CUSTOMER,customerpvo,".csv,.zip,.gz,.csv.gz",.csv,",",replace,1,first_chunk_only
```

### Step 4: Configure Component Settings from Templates
If deploying cleanly, generate active configuration files from their templates:
```bash
cd /sg/local/sid/home/Dsidadm/DATA_LOADER

# 1. Configure BICC Intake Controller
cp PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER/config_template.json \
   PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER/config.json

# 2. Configure Data Ingestion Orchestrator
cp PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/config_template.json \
   PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/config.json
```
Ensure `orchestration.max_global_utility_slots` (default `8`) in `PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/config.json` aligns with Teradata appliance workload management (TASM) throttles for concurrent load utilities.

### Step 5: Enforce POSIX Execution Permissions
Ensure all shell scripts and Python entrypoints have executable permissions:
```bash
chmod +x /sg/local/sid/home/Dsidadm/DATA_LOADER/collect_env_info.sh \
         /sg/local/sid/home/Dsidadm/DATA_LOADER/PROCESSING_TOOLS/TPT_LOADER/*.sh \
         /sg/local/sid/home/Dsidadm/DATA_LOADER/PROCESSING_TOOLS/TPT_LOADER/lib/*.sh \
         /sg/local/sid/home/Dsidadm/DATA_LOADER/TESTS/*.sh \
         /sg/local/sid/home/Dsidadm/DATA_LOADER/TESTS/scenarios/*.sh
```

---

## 5. Deployment Verification & Smoke Testing

### 5.1 Running the Automated Test Suite (Recommended)
The safest and most thorough way to verify the installation is running the automated test suite against Teradata Vantage:
```bash
cd /sg/local/sid/home/Dsidadm/DATA_LOADER/TESTS

# Run Scenario 1 (Nominal end-to-end pipeline)
./run_all_tests.sh --scenario 1

# Or run the full suite (Scenarios 1 through 11)
python3 run_all_tests.py
```

### 5.2 Manual Smoke Test with Pre-Packaged Synthetic Batch
Alternatively, run a manual smoke test using the pre-packaged nominal dataset:
```bash
# 1. Copy synthetic test batch into source-partitioned DROP_ZONE
cp /sg/local/sid/home/Dsidadm/DATA_LOADER/TESTS/DATASETS/BATCH_NOMINAL/* \
   /sg/local/sid/home/Dsidadm/DATA_LOADER/DATA/DROP_ZONE/ORACLE_FUSION/

# 2. Execute BICC Intake Controller
cd /sg/local/sid/home/Dsidadm/DATA_LOADER/PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER
python3 feeder.py --config config.json --source ORACLE_FUSION
```

### Validation Checklist
- [x] Process exits with code `0`.
- [x] Feeder log in `LOGS/ORACLE_FUSION/LOG_FEEDER_ORACLE_FUSION_<EXEC_TS>.log` confirms `[SUCCESS] Pipeline completed successfully`.
- [x] Orchestrator log generated in `LOGS/ORACLE_FUSION/<YYYY-MM>/BATCH_<ID>_<TS>/LOG_ORCHESTRATOR_ORACLE_FUSION_<EXTRACT_TS>_<BATCH_ID>_<EXEC_TS>.log`.
- [x] Batch Capsule created in `DATA/ARCHIVE_ZONE/ORACLE_FUSION/<YYYY-MM>/BATCH_<ID>_<TS>/` containing payload files, standardized manifest, `batch_descriptor.json`, and `RAW/` receipt.
- [x] Rows exist in `${TDENV}SIDFINTCH.BATCH_RUNS` with `STATUS = 'SUCCESS'` and `PROCESS_PID` retained.
- [x] Rows exist in target staging tables with `INFA_BATCH_ID` and `INFA_LAST_REPLICATED` populated.

---

## 6. Promotion, Upgrade & Rollback Procedures

### 6.1 Safe Upgrade Strategy
1. **Check for Running Batches**:
   ```sql
   SELECT COUNT(*) FROM DEV0SIDFINTCH.BATCH_RUNS WHERE STATUS = 'RUNNING';
   ```
   Do NOT deploy updates while batches are running.
2. **Backup Current Codebase (excluding runtime data and logs)**:
   ```bash
   tar --exclude="DATA" --exclude="LOGS" \
       -czf /sg/local/sid/home/Dsidadm/backup_DATA_LOADER_$(date +%Y%m%d_%H%M%S).tar.gz \
       -C /sg/local/sid/home/Dsidadm DATA_LOADER
   ```
3. **Deploy Code Artifacts**:
   Extract new release tarball into `/sg/local/sid/home/Dsidadm/DATA_LOADER/`.
4. **Preserve Runtime Data**:
   Never overwrite runtime directories `DATA/`, `LOGS/`, or customized routing `CONFIG/entity_mapping.csv`.

### 6.2 Rollback Procedure
If the upgrade encounters issues:
```bash
# 1. Stop any lingering processes
killall python3 tbuild 2>/dev/null || true

# 2. Restore previous codebase version
tar -xzf /sg/local/sid/home/Dsidadm/backup_DATA_LOADER_<TIMESTAMP>.tar.gz -C /sg/local/sid/home/Dsidadm/
```
