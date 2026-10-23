#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
DATA_LOADER - PYTHON TEST RUNNER (UNIX / LINUX)
=============================================================================
Wraps and executes test scenarios in DATA_LOADER/TESTS/scenarios/
and captures all console outputs and artifacts into DATA_LOADER/TESTS/OUTPUTS/
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
    parser.add_argument("--clean", action="store_true", help="Clean DATA and LOGS directories only")
    args = parser.parse_args()

    print_banner()

    if args.clean:
        clean_environment()
        sys.exit(0)

    summary_records = []

    if args.scenario:
        success = run_scenario(args.scenario, summary_records)
        bundle_outputs(summary_records)
        sys.exit(0 if success else 1)

    print(f"Running all {len(SCENARIOS)} scenarios sequentially...")
    failed = 0
    for s in sorted(SCENARIOS.keys()):
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
