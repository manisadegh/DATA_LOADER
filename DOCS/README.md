# DATA_LOADER - Enterprise Documentation Suite

Welcome to the central documentation repository for the **DATA_LOADER** flat-file ELT ingestion framework for **Teradata Vantage**.

This documentation suite serves as the definitive Single Source of Truth (SSoT), verified directly against the production codebase deployed at `/sg/local/sid/home/Dsidadm/DATA_LOADER`.

---

## Architecture at a Glance

```mermaid
flowchart LR
    Upstream["Oracle Fusion Cloud BICC"] -->|Asynchronous Exports| Tier1
    
    subgraph Tier1["1. BICC_INTAKE_CONTROLLER"]
        direction TB
        F1["FIFO Chronological Queue"]
        F2["Stability Sentry (>0 bytes)"]
        F3["Zero Teradata Dependency (In-Memory Headers)"]
        F4["Manifest Factory & Capsule Publishing"]
    end

    Tier1 -->|Publishes Batch Capsules| Tier2

    subgraph Tier2["2. DATA_INGESTION_ORCHESTRATOR"]
        direction TB
        O1["Multi-Batch FIFO Queue Consumer"]
        O2["Fast-Path O(1) Descriptor Check"]
        O3["JIT Schema Guard & Auto-DDL"]
        O4["ThreadPool Parallel Entity Dispatch"]
    end

    Tier2 -->|Invoke per Entity (-C -M 2)| Tier3

    subgraph Tier3["3. TPT_LOADER"]
        direction TB
        T1["Fast-Path BTEQ Bypass (-C -M 2)"]
        T2["Dynamic Schema (FROM TABLE DELIMITED)"]
        T3["FastLoad / MultiLoad Execution"]
        T4["Audit Metadata Backfill (INFA_*)"]
    end

    Tier3 -->|Wire-Speed Load| Teradata["Teradata Vantage (${TDENV}SIDFINSTG)"]
```

---

## Documentation Navigation Matrix

The documentation suite comprises eighteen (18) detailed guides categorized into shared SDK references, component-level manuals, developer tutorials, and system-level operational documents:

### Category 0: COMMON_CORE_SDK (`dataloader_core` Shared Library)
| Document | Title | Target Audience | Focus Area |
|---|---|---|---|
| **[DOC-00.1]** | [Shared Core SDK Technical Reference](00_COMMON_CORE_SDK/01_dataloader_core_technical_reference.md) | Core Maintainers, Architects | `ConfigLoader`, `ProcessLock` (`fcntl.flock`), `TeradataConnectionManager` pool, `EntityMapper`, `ManifestHandler`, `CapsulePathResolver`, `schema_reader`. |
| **[DOC-00.2]** | [Onboarding New Data Sources Developer Guide](00_COMMON_CORE_SDK/02_onboarding_new_data_sources_guide.md) | Developers, Architects | `SourceIntakePlugin` framework, 9-column entity mapping, custom plugins, CLI workflows, and testing. |

---

### Category A: BICC_INTAKE_CONTROLLER (Tier 1 Feeder)
| Document | Title | Target Audience | Focus Area |
|---|---|---|---|
| **[DOC-01]** | [User How-To & Configuration Guide](01_BICC_INTAKE_CONTROLLER/01_user_how_to_guide.md) | Developers, Operators | CLI flags (`--enqueue-only`), `config.json` options, log reading, troubleshooting. |
| **[DOC-02]** | [Functional Specification](01_BICC_INTAKE_CONTROLLER/02_functional_specification.md) | Analysts, Leads | Business logic, FIFO queueing, pure intake producer role, Batch Capsule publishing, `FAIL_STOP`. |
| **[DOC-03]** | [Technical Manual & Inventory](01_BICC_INTAKE_CONTROLLER/03_technical_manual_and_inventory.md) | Core Maintainers | Internal code architecture, module inventory (`intake_service`, `scanner`, `manifest_factory`), functions. |
| **[DOC-04]** | [Testing, Validation & QA Guide](01_BICC_INTAKE_CONTROLLER/04_testing_and_qa_guide.md) | QA, Test Engineers | Test scenarios, multi-batch FIFO validation, `--enqueue-only` tests, stability sentry tests. |

---

### Category B: DATA_INGESTION_ORCHESTRATOR (Tier 2 Orchestrator)
| Document | Title | Target Audience | Focus Area |
|---|---|---|---|
| **[DOC-05]** | [User How-To & Configuration Guide](02_DATA_INGESTION_ORCHESTRATOR/01_user_how_to_guide.md) | Developers, Operators | Multi-batch FIFO queue draining, JIT Schema Guard config, source-keyed post-tasks, log inspection. |
| **[DOC-06]** | [Functional Specification](02_DATA_INGESTION_ORCHESTRATOR/02_functional_specification.md) | Architects, Leads | Multi-batch FIFO queue consumption (OPS-01), JIT Schema Guard Auto-DDL, Solution A multi-chunk header stripping. |
| **[DOC-07]** | [Technical Manual & Inventory](02_DATA_INGESTION_ORCHESTRATOR/03_technical_manual_and_inventory.md) | Core Maintainers | Module breakdowns (`schema_guard`, `sensor`, `db_state`, `tpt_worker`, `post_tasks`), state DDL. |
| **[DOC-08]** | [Testing, Validation & QA Guide](02_DATA_INGESTION_ORCHESTRATOR/04_testing_and_qa_guide.md) | QA, Test Engineers | Multi-batch queue tests, JIT Schema Guard drift tests, Error 2652 reactive lock recovery tests. |

---

### Category C: TPT_LOADER (Tier 3 Ingestion Engine)
| Document | Title | Target Audience | Focus Area |
|---|---|---|---|
| **[DOC-09]** | [User How-To & CLI Reference](03_TPT_LOADER/01_user_how_to_guide.md) | Developers, Operators | CLI arguments (`-f`, `-t`, `-m`, `-B`, `-T`, `-C`, `-M`), job variables, unlock usage. |
| **[DOC-10]** | [Functional Specification](03_TPT_LOADER/02_functional_specification.md) | Architects, DBAs | Dynamic schema derivation, FastLoad vs MultiLoad, fast-path BTEQ pre-check bypass, audit backfill. |
| **[DOC-11]** | [Technical Manual & Inventory](03_TPT_LOADER/03_technical_manual_and_inventory.md) | Core Maintainers | POSIX bash framework, `generate_jobvars.sh`, TPT template, BTEQ scripts, `-C` and `-M` handling. |
| **[DOC-12]** | [Testing, Validation & QA Guide](03_TPT_LOADER/04_testing_and_qa_guide.md) | QA, Test Engineers | DAT-01 column order tests, DAT-02 append checks, fast-path bypass tests, lock recovery tests. |

---

### Category D: DATA_LOADER SYSTEM-LEVEL (Global Framework)
| Document | Title | Target Audience | Focus Area |
|---|---|---|---|
| **[DOC-13]** | [Enterprise Architecture Specification](04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/01_enterprise_architecture_specification.md) | Solution Architects | End-to-end 3-tier cascade, storage lifecycle, batch capsule architecture, system invariants. |
| **[DOC-14]** | [Deployment & Installation Guide](04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/02_deployment_and_installation_guide.md) | DevOps, Sysadmins | Multi-environment promotion, profile exports, step-by-step setup, 11-scenario automated validation (100% PASS). |
| **[DOC-15]** | [Operations Playbook & Technical FAQ](04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/03_production_operations_playbook_and_faq.md) | L2/L3 Support, DBAs | 7 actionable emergency runbooks, routine schedules, comprehensive FAQ. |

---

### Category E: SOURCE INTAKE CONTROLLER DEVELOPMENT (Extension & Custom Feeder Guide)
| Document | Title | Target Audience | Focus Area |
|---|---|---|---|
| **[DOC-16]** | [Step-by-Step Custom Intake Controller Tutorial](05_SOURCE_INTAKE_CONTROLLER_DEVELOPMENT_GUIDE/01_step_by_step_intake_controller_development_tutorial.md) | Developers, Data Engineers, Architects | End-to-end tutorial for building source-specific intake controllers, SourceIntakePlugin, 9-column entity mapping, FIFO queueing, stability sentries, in-memory headers, testing, and production deployment. |

---

## Recommended Reading Paths

- **For Business Analysts & Architects**:
  Read [DOC-13](04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/01_enterprise_architecture_specification.md) $\rightarrow$ [DOC-02](01_BICC_INTAKE_CONTROLLER/02_functional_specification.md) $\rightarrow$ [DOC-06](02_DATA_INGESTION_ORCHESTRATOR/02_functional_specification.md) $\rightarrow$ [DOC-10](03_TPT_LOADER/02_functional_specification.md).
- **For Production Support & Sysadmins**:
  Read [DOC-15](04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/03_production_operations_playbook_and_faq.md) $\rightarrow$ [DOC-14](04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/02_deployment_and_installation_guide.md) $\rightarrow$ [DOC-01](01_BICC_INTAKE_CONTROLLER/01_user_how_to_guide.md).
- **For Software Engineers & Maintainers**:
  Read [DOC-00](00_COMMON_CORE_SDK/01_dataloader_core_technical_reference.md) $\rightarrow$ [DOC-03](01_BICC_INTAKE_CONTROLLER/03_technical_manual_and_inventory.md) $\rightarrow$ [DOC-07](02_DATA_INGESTION_ORCHESTRATOR/03_technical_manual_and_inventory.md) $\rightarrow$ [DOC-11](03_TPT_LOADER/03_technical_manual_and_inventory.md).
- **For QA & Test Automation Engineers**:
  Read [DOC-04](01_BICC_INTAKE_CONTROLLER/04_testing_and_qa_guide.md) $\rightarrow$ [DOC-08](02_DATA_INGESTION_ORCHESTRATOR/04_testing_and_qa_guide.md) $\rightarrow$ [DOC-12](03_TPT_LOADER/04_testing_and_qa_guide.md).
- **For New Data Source Onboarding & Integration Engineers**:
  Read [DOC-00.2](00_COMMON_CORE_SDK/02_onboarding_new_data_sources_guide.md) $\rightarrow$ [DOC-16](05_SOURCE_INTAKE_CONTROLLER_DEVELOPMENT_GUIDE/01_step_by_step_intake_controller_development_tutorial.md) $\rightarrow$ [DOC-01](01_BICC_INTAKE_CONTROLLER/01_user_how_to_guide.md).
