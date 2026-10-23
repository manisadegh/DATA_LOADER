# Source Intake Controller Development Guide

Welcome to the **Source Intake Controller Development Guide** for the **DATA_LOADER** ELT platform.

This directory contains comprehensive, step-by-step developer documentation and tutorials designed to guide software engineers, data engineers, and architects in implementing, testing, and operationalizing new source-specific intake controllers.

---

## Documents in this Section

| Document | Description | Target Audience |
|:---|:---|:---|
| **[01_step_by_step_intake_controller_development_tutorial.md](01_step_by_step_intake_controller_development_tutorial.md)** | Full end-to-end tutorial detailing the development of a production-grade intake controller using SAP_ERP as a concrete reference implementation. | Developers, Data Engineers, Architects |

---

## Architectural Context

In the DATA_LOADER 3-tier cascade:
1. **Tier 1: Intake Controller (Producer)** - Scans drop zones, verifies file stability, reads headers in-memory (zero-disk extraction), computes MD5 checksums, stages atomic capsules into LANDING_ZONE/<SOURCE>/BATCH_<TS>_<ID>/, and maintains zero Teradata database dependencies.
2. **Tier 2: Ingestion Orchestrator (Consumer)** - Consumes queued capsules in strict FIFO order, executes fast-path (1)$ batch descriptor verification, synchronizes schema via Just-In-Time Schema Guard (DBC.ColumnsV), and dispatches parallel entity loads under Teradata UtilitySlotGovernor.
3. **Tier 3: TPT Loader Engine (Execution)** - Executes high-speed Teradata Parallel Transporter (	build) jobs using dynamic schemas and backfills audit metadata.

---

## What This Guide Covers

- **Architectural Rules & Golden Guidelines**: Zero Teradata dependency in Tier 1, strict FAIL_STOP semantics, $< 80$-line entrypoints, and POSIX compliance.
- **Three Integration Strategies**:
  - *Strategy A*: Built-in Plugin (No-Code, configuration only).
  - *Strategy B*: Custom Intake Plugin subclassing SourceIntakePlugin.
  - *Strategy C*: Dedicated Standalone Intake Controller subclassing BaseIntakeController.
- **Concrete Reference Implementation (SAP_ERP)**:
  - Storage tier partitioning (DATA/*_ZONE/SAP_ERP, LOGS/SAP_ERP).
  - 9-column entity mapping dictionary in CONFIG/entity_mapping.csv.
  - Custom plugin implementation with pipe-delimited raw manifest parsing.
  - Thin CLI entrypoint (eeder.py) and JSON configuration (config.json).
- **Comprehensive Testing & Validation**:
  - Isolated unit tests (unittest).
  - Decoupled --enqueue-only producer verification.
  - Multi-batch FIFO consumer verification via orchestrator.py.
- **Production Deployment & Automation**:
  - Crontab scheduling (synchronous vs decoupled producer/consumer).
  - Pre-flight deployment checklist.
