# Source Intake Controller Development Guide

Welcome to the **Source Intake Controller Development Guide** for the **DATA_LOADER** ELT platform.

This directory contains comprehensive, step-by-step developer documentation and tutorials designed to guide software engineers, data engineers, and architects in implementing, testing, and operationalizing new source-specific intake controllers across three distinct integration strategies.

---

## Documents in this Section

| Document | Description | Target Audience |
|:---|:---|:---|
| **[01_step_by_step_intake_controller_development_tutorial.md](01_step_by_step_intake_controller_development_tutorial.md)** | Authoritative guide detailing Strategy Selection (A, B, and C), comprehensive decision matrix, and complete step-by-step implementations for NetSuite (Strategy A), Workday (Strategy B), and SAP ERP (Strategy C). | Developers, Data Engineers, Architects |

---

## Architectural Context

In the `DATA_LOADER` 3-tier cascade:
1. **Tier 1: Intake Controller (Producer)** - Scans drop zones, verifies file stability, reads headers in-memory (zero-disk extraction), computes MD5 checksums, stages atomic capsules into `LANDING_ZONE/<SOURCE>/BATCH_<TS>_<ID>/`, and maintains zero Teradata database dependencies.
2. **Tier 2: Ingestion Orchestrator (Consumer)** - Consumes queued capsules in strict FIFO order, executes fast-path $O(1)$ batch descriptor verification, synchronizes schema via Just-In-Time Schema Guard (`DBC.ColumnsV`), and dispatches parallel entity loads under Teradata `UtilitySlotGovernor`.
3. **Tier 3: TPT Loader Engine (Execution)** - Executes high-speed Teradata Parallel Transporter (`tbuild`) jobs using dynamic schemas and backfills audit metadata.

---

## What This Guide Covers

- **Architectural Rules & Golden Principles**: Zero Teradata dependency in Tier 1, strict `FAIL_STOP` semantics, $< 80$-line entrypoints, and POSIX compliance.
- **Decision Matrix & Decision Tree**: Clear decision tree flowchart and trade-off criteria to determine when to adopt Strategy A, Strategy B, or Strategy C.
- **Three Concrete Strategy Walkthroughs**:
  - **Strategy A (Zero-Code / Config Only)**: Onboarding `NETSUITE` (standard manifests) and `SALESFORCE` (manifestless drops) using built-in plugins in 0 lines of Python.
  - **Strategy B (Custom Intake Plugin)**: Onboarding `WORKDAY` (custom JSON manifests) by subclassing `SourceIntakePlugin` and registering via `PluginRegistry`.
  - **Strategy C (Dedicated Standalone Controller)**: Building a full autonomous controller for `SAP_ERP` with dedicated service, thin CLI entrypoint, and custom configuration.
- **Comprehensive Testing & Validation**:
  - Isolated unit tests (`unittest.TestCase`).
  - Decoupled `--enqueue-only` producer verification.
  - Multi-batch FIFO consumer verification via `orchestrator.py`.
- **Production Deployment & Automation**:
  - Crontab scheduling (synchronous vs decoupled producer/consumer).
  - Production quality gates checklist.
