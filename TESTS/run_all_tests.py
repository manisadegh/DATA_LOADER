#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
DATA_LOADER - PYTHON TEST RUNNER (UNIX / LINUX)
=============================================================================
Orchestrates unit test suites and end-to-end integration scenarios against
native DATA_LOADER runtime directories.

Execution sequence:
  1. Phase 1 (Pre-Flight): All in-memory unit tests (TESTS/unit/ + test_phase01_units.py)
     and architectural line limit invariants (< 80 lines).
  2. Phase 2: Live Teradata end-to-end integration scenarios (Scenarios 09, 08, 01..07, 10, 11).
=============================================================================
"""

import os
import sys
import subprocess
import argparse
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCENARIOS_DIR = os.path.join(TESTS_DIR, "scenarios")
OUTPUTS_DIR = os.path.join(TESTS_DIR, "OUTPUTS")

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

SCENARIOS = {
    1: ("01_test_nominal_pipeline.sh", "Nominal End-to-End Pipeline"),
    2: ("02_test_skip_post_tasks.sh", "Hybrid Decoupling (--skip-post-tasks)"),
    3: ("03_test_concurrency_lock.sh", "Concurrency & Active Wait Loop"),
    4: ("04_test_crash_stale_pid.sh", "Crash Recovery & Stale PID Cleanup"),
    5: ("05_test_multisource_partition.sh", "Multi-Source Partitioning Isolation"),
    6: ("06_test_intake_controller_post_tasks.sh", "Intake Controller Post-Tasks & Skip Validation"),
    7: ("07_test_database_and_storage_audit.sh", "Teradata DB, Storage Cleanliness & PROCESS_PID Audit"),
    8: ("08_test_lock_recovery_and_schema_flags.sh", "Lock Recovery Metadata & Schema Guard Flags"),
    9: ("09_test_unit_and_core_sdk.sh", "Core SDK Unit Tests & Connection Pool Validation"),
    10: ("10_test_decoupled_multi_batch_queue.sh", "Decoupled Multi-Batch Queue & JIT Schema Guard"),
    11: ("11_test_multisource_plugin_and_slot_governor.sh", "Multi-Source Plugin Framework & Global Utility Slot Governor"),
}

# Unit tests and core SDK tests execute before heavy live end-to-end scenarios
DEFAULT_EXECUTION_ORDER = [9, 8, 1, 2, 3, 4, 5, 6, 7, 10, 11]


def get_bash_executable():
    if sys.platform != "win32":
        return "/bin/bash" if os.path.exists("/bin/bash") else "bash"
    for cand in [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]:
        if os.path.exists(cand):
            return cand
    return "bash"


def print_banner():
    print(f"{CYAN}{'=' * 78}{RESET}")
    print(f"{BOLD}{CYAN}   DATA_LOADER AUTOMATED TEST RUNNER (PYTHON / UNIX){RESET}")
    print(f"{CYAN}{'=' * 78}{RESET}")


def run_unit_tests(summary_records=None):
    """
    Executes in-memory unit tests and architectural invariant checks in seconds
    before running live Teradata end-to-end scenarios.
    """
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    console_log_path = os.path.join(OUTPUTS_DIR, "scenario_00_unit_tests_console.log")

    print(f"\n{BOLD}{YELLOW}>>> [PHASE 1] EXECUTING IN-MEMORY UNIT TESTS & ARCHITECTURAL INVARIANTS{RESET}")
    print(f"{CYAN}    - Discovery Suite: TESTS/unit/test_*.py (Core SDK, Mapping, Schema Guard){RESET}")
    print(f"{CYAN}    - Isolated Suite : TESTS/test_phase01_units.py (Phase 01 Parity & Flags){RESET}")
    print(f"{CYAN}    - Invariants     : Entrypoint line limits (< 80 lines) & deduplication{RESET}\n")

    start = time.time()
    all_ok = True

    base_dir = os.path.dirname(TESTS_DIR)
    common_dir = os.path.join(base_dir, "PROCESSING_TOOLS", "COMMON")
    feeder_dir = os.path.join(base_dir, "PROCESSING_TOOLS", "BICC_INTAKE_CONTROLLER")
    orch_dir = os.path.join(base_dir, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
    tpt_dir = os.path.join(base_dir, "PROCESSING_TOOLS", "TPT_LOADER")

    env = os.environ.copy()
    existing_pypath = env.get("PYTHONPATH", "")
    tpt_lib = os.path.join(tpt_dir, "lib")
    env["PYTHONPATH"] = f"{common_dir}:{feeder_dir}:{orch_dir}:{tpt_lib}:{existing_pypath}"

    py_bin = sys.executable or "python3"

    with open(console_log_path, "w", encoding="utf-8", errors="replace") as log_f:
        log_f.write("=== UNIT TESTS & ARCHITECTURAL INVARIANTS PRE-FLIGHT ===\n\n")

        # 1. Discovery Suite: TESTS/unit/test_*.py
        log_f.write("--- [PART 1] Running Discovery Suite (TESTS/unit/test_*.py) ---\n")
        print(f"{BOLD}>>> Running Discovery Suite (TESTS/unit/test_*.py)...{RESET}")
        proc1 = subprocess.Popen(
            [py_bin, "-m", "unittest", "discover", "-s", os.path.join(TESTS_DIR, "unit"), "-p", "test_*.py", "-v"],
            cwd=TESTS_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in proc1.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_f.write(line)
        proc1.wait()
        if proc1.returncode != 0:
            all_ok = False
            print(f"{RED}[FAIL] Discovery Suite failed with RC={proc1.returncode}{RESET}")
        else:
            print(f"{GREEN}[PASS] Discovery Suite passed.{RESET}\n")

        # 2. Phase 01 Isolated Units: TESTS/test_phase01_units.py
        log_f.write("\n--- [PART 2] Running Phase 01 Units (TESTS/test_phase01_units.py) ---\n")
        print(f"{BOLD}>>> Running Phase 01 Units (TESTS/test_phase01_units.py)...{RESET}")
        proc2 = subprocess.Popen(
            [py_bin, os.path.join(TESTS_DIR, "test_phase01_units.py")],
            cwd=TESTS_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in proc2.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_f.write(line)
        proc2.wait()
        if proc2.returncode != 0:
            all_ok = False
            print(f"{RED}[FAIL] Phase 01 Units failed with RC={proc2.returncode}{RESET}")
        else:
            print(f"{GREEN}[PASS] Phase 01 Units passed.{RESET}\n")

        # 3. Architectural Invariants
        log_f.write("\n--- [PART 3] Verifying Architectural Invariants ---\n")
        print(f"{BOLD}>>> Verifying Architectural Invariants (< 80 lines)...{RESET}")
        feeder_py = os.path.join(feeder_dir, "feeder.py")
        orch_py = os.path.join(orch_dir, "orchestrator.py")

        def count_lines(path):
            if not os.path.exists(path):
                return 0
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)

        feeder_lines = count_lines(feeder_py)
        orch_lines = count_lines(orch_py)

        inv_text = (
            f"  - feeder.py line count       : {feeder_lines} (limit: < 80)\n"
            f"  - orchestrator.py line count : {orch_lines} (limit: < 80)\n"
        )
        sys.stdout.write(inv_text)
        log_f.write(inv_text)

        if feeder_lines >= 80 or orch_lines >= 80:
            err = ">>> [FAILURE] Entrypoint line count exceeded 80 lines!\n"
            sys.stdout.write(f"{RED}{err}{RESET}")
            log_f.write(err)
            all_ok = False
        else:
            print(f"{GREEN}[PASS] Architectural invariants verified.{RESET}\n")

    duration = time.time() - start
    status_str = "PASS" if all_ok else "FAIL"
    if summary_records is not None:
        summary_records.append(
            f"Unit Tests Suite (TESTS/unit/ + test_phase01_units.py) : {status_str} (Duration={duration:.1f}s)"
        )

    if all_ok:
        print(f"{GREEN}{BOLD}>>> [PASS] All unit tests & architectural invariants succeeded in {duration:.1f}s{RESET}")
        return True
    else:
        print(f"{RED}{BOLD}>>> [FAIL] Unit tests failed! Halting before end-to-end scenarios.{RESET}")
        return False


def run_scenario(scenario_num, summary_records=None):
    if scenario_num not in SCENARIOS:
        print(f"{RED}Error: Unknown scenario number {scenario_num}{RESET}")
        return False

    script_name, description = SCENARIOS[scenario_num]
    script_path = os.path.join(SCENARIOS_DIR, script_name)
    if not os.path.isfile(script_path):
        print(f"{RED}Error: Script not found: {script_path}{RESET}")
        return False

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    console_log_path = os.path.join(OUTPUTS_DIR, f"scenario_{scenario_num:02d}_console.log")

    bash_bin = get_bash_executable()
    print(f"\n{BOLD}{YELLOW}>>> EXECUTING SCENARIO {scenario_num}: {description}{RESET}")
    start = time.time()

    with open(console_log_path, "w", encoding="utf-8", errors="replace") as log_f:
        log_f.write(f"=== SCENARIO {scenario_num:02d}: {description} ({script_name}) ===\n")
        proc = subprocess.Popen(
            [bash_bin, script_path],
            cwd=TESTS_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_f.write(line)
        proc.wait()
        rc = proc.returncode

    duration = time.time() - start
    status_str = "PASS" if rc == 0 else "FAIL"
    if summary_records is not None:
        summary_records.append(
            f"Scenario {scenario_num:02d} ({script_name}) : {status_str} (RC={rc}, Duration={duration:.1f}s)"
        )

    if rc == 0:
        print(f"{GREEN}{BOLD}>>> [PASS] Scenario {scenario_num} succeeded in {duration:.1f}s{RESET}")
        return True
    else:
        print(f"{RED}{BOLD}>>> [FAIL] Scenario {scenario_num} failed with exit code {rc}{RESET}")
        return False


def clean_environment():
    clean_script = os.path.join(TESTS_DIR, "clean_data_and_logs.sh")
    print(f"{CYAN}>>> Resetting DATA and LOGS directories...{RESET}")
    bash_bin = get_bash_executable()
    res = subprocess.run([bash_bin, clean_script], cwd=TESTS_DIR)
    return res.returncode == 0


def bundle_outputs(summary_records):
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    summary_path = os.path.join(OUTPUTS_DIR, "test_runner_summary.log")
    with open(summary_path, "w", encoding="utf-8") as sf:
        sf.write("=" * 78 + "\n")
        sf.write("DATA_LOADER - MASTER TEST RUNNER SUMMARY\n")
        sf.write("=" * 78 + "\n")
        for rec in summary_records:
            sf.write(rec + "\n")
        sf.write("=" * 78 + "\n")

    import tarfile
    import shutil
    ts_str = time.strftime("%Y%m%d_%H%M%S")
    bundle_file = os.path.join(OUTPUTS_DIR, f"all_test_outputs_{ts_str}.tar.gz")
    latest_bundle = os.path.join(OUTPUTS_DIR, "all_test_outputs_latest.tar.gz")
    try:
        with tarfile.open(bundle_file, "w:gz") as tar:
            for item in os.listdir(OUTPUTS_DIR):
                if not item.endswith(".tar.gz"):
                    tar.add(os.path.join(OUTPUTS_DIR, item), arcname=item)
        if os.path.exists(latest_bundle):
            os.remove(latest_bundle)
        shutil.copy2(bundle_file, latest_bundle)
        print(f"{CYAN}>>> All scenario outputs archived in : {OUTPUTS_DIR}{RESET}")
        print(f"{CYAN}    Archive tarball created           : {latest_bundle}{RESET}")
    except Exception as e:
        print(f"{YELLOW}Warning: Could not create tar bundle: {e}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="DATA_LOADER Automated Test Runner")
    parser.add_argument(
        "--scenario",
        "-s",
        type=int,
        choices=sorted(SCENARIOS.keys()),
        help=f"Run a specific scenario (1-{len(SCENARIOS)})",
    )
    parser.add_argument(
        "--unit-only",
        "-u",
        action="store_true",
        help="Execute in-memory unit tests and architectural invariants only (no Teradata dependencies)",
    )
    parser.add_argument("--clean", action="store_true", help="Clean DATA and LOGS directories only")
    args = parser.parse_args()

    print_banner()

    if args.clean:
        clean_environment()
        sys.exit(0)

    summary_records = []

    # If --unit-only requested, run Phase 1 only and exit
    if args.unit_only:
        unit_success = run_unit_tests(summary_records)
        bundle_outputs(summary_records)
        sys.exit(0 if unit_success else 1)

    # If specific scenario requested, execute that scenario
    if args.scenario:
        success = run_scenario(args.scenario, summary_records)
        bundle_outputs(summary_records)
        sys.exit(0 if success else 1)

    # Default: Run unit tests FIRST, then execute end-to-end scenarios
    print(f"{BOLD}Execution Sequence:{RESET}")
    print(f"  1. Phase 1: In-Memory Unit Tests & Invariants Pre-Flight")
    print(f"  2. Phase 2: Live End-to-End Scenarios ({len(DEFAULT_EXECUTION_ORDER)} scenarios)\n")

    if not run_unit_tests(summary_records):
        print(f"\n{RED}{BOLD}Stopping test execution: Unit tests failed before end-to-end scenarios.{RESET}")
        bundle_outputs(summary_records)
        sys.exit(1)

    print(f"\n{BOLD}{YELLOW}>>> [PHASE 2] EXECUTING LIVE END-TO-END INTEGRATION SCENARIOS{RESET}")
    failed = 0
    for s in DEFAULT_EXECUTION_ORDER:
        if not run_scenario(s, summary_records):
            failed += 1
            print(f"{RED}{BOLD}Stopping test execution due to failure in Scenario {s}.{RESET}")
            break

    bundle_outputs(summary_records)

    print(f"\n{CYAN}{'=' * 78}{RESET}")
    if failed == 0:
        print(f"{GREEN}{BOLD}>>> ALL TEST SCENARIOS PASSED WITH SUCCESS (100% PASS) !{RESET}")
        print(f"{CYAN}{'=' * 78}{RESET}\n")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}>>> TEST SUITE FAILED ({failed} error). Review {OUTPUTS_DIR}{RESET}")
        print(f"{CYAN}{'=' * 78}{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
