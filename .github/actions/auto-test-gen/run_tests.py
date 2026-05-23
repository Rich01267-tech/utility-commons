#!/usr/bin/env python3
"""
run_tests.py — Test Runner and Coverage Collector
==================================================
Executes the generated test cases for each detected service,
collects pass/fail results per test case, generates coverage
reports, and outputs structured results for the PR comment step.

Supports:
  - FastAPI  → pytest + pytest-cov
  - Next.js  → Jest + coverage
  - Node/Express → Jest + Supertest + coverage
"""

import os
import sys
import json
import subprocess
import re
from pathlib import Path


# ── Environment variables ─────────────────────────────────────────────────────

TEST_OUTPUT_DIR      = os.environ.get("TEST_OUTPUT_DIR", "__generated_tests__")
DETECTED_SERVICES    = os.environ.get("DETECTED_SERVICES", "[]")
COVERAGE_THRESHOLD   = float(os.environ.get("COVERAGE_THRESHOLD", "80"))
FAIL_ON_TEST_FAILURE = os.environ.get("FAIL_ON_TEST_FAILURE", "true").lower() == "true"
GITHUB_OUTPUT        = os.environ.get("GITHUB_OUTPUT", "/dev/stdout")


# ── Test runners ──────────────────────────────────────────────────────────────

def run_pytest(test_dir: str) -> dict:
    """
    Run pytest on generated Python test files.
    Returns structured results with per-test pass/fail data.
    """
    print(f"  Running pytest on {test_dir}...")

    # Find all test files
    test_files = list(Path(test_dir).rglob("test_*.py"))
    if not test_files:
        return {"status": "no_tests", "tests": [], "coverage": 0.0}

    test_paths = [str(f) for f in test_files]

    cmd = [
        "python", "-m", "pytest",
        *test_paths,
        "--tb=short",
        "--no-header",
        "-v",
        f"--cov={os.getcwd()}",
        "--cov-report=json:coverage.json",
        "--cov-report=term-missing",
        "--json-report",
        "--json-report-file=pytest_report.json",
        "-p", "no:warnings",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    stdout = result.stdout
    stderr = result.stderr

    print(stdout[-3000:] if len(stdout) > 3000 else stdout)
    if stderr:
        print("STDERR:", stderr[-1000:])

    # Parse pytest JSON report
    tests_data   = []
    passed_count = 0
    failed_count = 0

    report_path = Path("pytest_report.json")
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())
            for test in report.get("tests", []):
                node_id  = test.get("nodeid", "")
                outcome  = test.get("outcome", "failed")
                duration = test.get("duration", 0)

                # Extract function name from node ID
                func_name = node_id.split("::")[-1] if "::" in node_id else node_id

                test_entry = {
                    "name":     func_name,
                    "node_id":  node_id,
                    "outcome":  outcome,
                    "duration": round(duration, 3),
                    "passed":   outcome == "passed",
                }

                # Capture failure reason
                if outcome == "failed":
                    call_info = test.get("call", {})
                    longrepr  = call_info.get("longrepr", "")
                    test_entry["failure_reason"] = longrepr[:500] if longrepr else "Unknown failure"
                    failed_count += 1
                else:
                    passed_count += 1

                tests_data.append(test_entry)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not parse pytest JSON report: {e}")
            # Fall back to stdout parsing
            tests_data, passed_count, failed_count = parse_pytest_stdout(stdout)
    else:
        tests_data, passed_count, failed_count = parse_pytest_stdout(stdout)

    # Parse coverage
    coverage_pct = parse_coverage_json("coverage.json")

    return {
        "status":        "completed",
        "tests":         tests_data,
        "passed":        passed_count,
        "failed":        failed_count,
        "total":         passed_count + failed_count,
        "coverage":      coverage_pct,
        "exit_code":     result.returncode,
    }


def parse_pytest_stdout(stdout: str) -> tuple[list, int, int]:
    """Fallback: parse pytest stdout when JSON report is unavailable."""
    tests   = []
    passed  = 0
    failed  = 0

    for line in stdout.split("\n"):
        if " PASSED" in line:
            name = line.split("::")[- 1].replace(" PASSED", "").strip()
            tests.append({"name": name, "passed": True, "outcome": "passed"})
            passed += 1
        elif " FAILED" in line:
            name = line.split("::")[-1].replace(" FAILED", "").strip()
            tests.append({"name": name, "passed": False, "outcome": "failed"})
            failed += 1
        elif " ERROR" in line:
            name = line.split("::")[-1].replace(" ERROR", "").strip()
            tests.append({"name": name, "passed": False, "outcome": "error"})
            failed += 1

    return tests, passed, failed


def run_jest(test_dir: str, service: str) -> dict:
    """
    Run Jest on generated TypeScript/JavaScript test files.
    Returns structured results with per-test pass/fail data.
    """
    print(f"  Running Jest on {test_dir}...")

    test_files = (
        list(Path(test_dir).rglob("*.test.tsx")) +
        list(Path(test_dir).rglob("*.test.ts"))  +
        list(Path(test_dir).rglob("*.test.jsx")) +
        list(Path(test_dir).rglob("*.test.js"))
    )

    if not test_files:
        return {"status": "no_tests", "tests": [], "coverage": 0.0}

    test_patterns = [str(f) for f in test_files]

    cmd = [
        "npx", "jest",
        "--testPathPattern", "|".join(
            re.escape(str(f)) for f in test_files
        ),
        "--coverage",
        "--coverageReporters", "json-summary",
        "--json",
        "--outputFile=jest_report.json",
        "--no-cache",
        "--forceExit",
        "--passWithNoTests",
    ]

    # Add Next.js specific config if needed
    if service == "nextjs":
        cmd += ["--testEnvironment", "jsdom"]
    else:
        cmd += ["--testEnvironment", "node"]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    stdout = result.stdout
    stderr = result.stderr

    print(stdout[-3000:] if len(stdout) > 3000 else stdout)
    if stderr:
        print("STDERR:", stderr[-1000:])

    # Parse Jest JSON report
    tests_data   = []
    passed_count = 0
    failed_count = 0

    report_path = Path("jest_report.json")
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text())

            for test_suite in report.get("testResults", []):
                suite_name = test_suite.get("testFilePath", "unknown")

                for assertion in test_suite.get("assertionResults", []):
                    test_title    = assertion.get("title", "unknown")
                    ancestor_titles = assertion.get("ancestorTitles", [])
                    full_name     = " > ".join(ancestor_titles + [test_title])
                    status        = assertion.get("status", "failed")
                    duration      = assertion.get("duration", 0)

                    test_entry = {
                        "name":     full_name,
                        "suite":    suite_name,
                        "outcome":  status,
                        "duration": round((duration or 0) / 1000, 3),
                        "passed":   status == "passed",
                    }

                    if status == "failed":
                        failure_messages = assertion.get("failureMessages", [])
                        test_entry["failure_reason"] = (
                            failure_messages[0][:500] if failure_messages else "Unknown failure"
                        )
                        failed_count += 1
                    else:
                        passed_count += 1

                    tests_data.append(test_entry)

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not parse Jest JSON report: {e}")
            tests_data, passed_count, failed_count = parse_jest_stdout(stdout)
    else:
        tests_data, passed_count, failed_count = parse_jest_stdout(stdout)

    # Parse coverage from Jest coverage-summary.json
    coverage_pct = parse_jest_coverage()

    return {
        "status":    "completed",
        "tests":     tests_data,
        "passed":    passed_count,
        "failed":    failed_count,
        "total":     passed_count + failed_count,
        "coverage":  coverage_pct,
        "exit_code": result.returncode,
    }


def parse_jest_stdout(stdout: str) -> tuple[list, int, int]:
    """Fallback: parse Jest stdout when JSON report is unavailable."""
    tests  = []
    passed = 0
    failed = 0

    for line in stdout.split("\n"):
        if line.strip().startswith("✓") or line.strip().startswith("√"):
            name = line.strip().lstrip("✓√").strip()
            tests.append({"name": name, "passed": True, "outcome": "passed"})
            passed += 1
        elif line.strip().startswith("✕") or line.strip().startswith("×"):
            name = line.strip().lstrip("✕×").strip()
            tests.append({"name": name, "passed": False, "outcome": "failed"})
            failed += 1

    return tests, passed, failed


# ── Coverage parsers ──────────────────────────────────────────────────────────

def parse_coverage_json(coverage_file: str) -> float:
    """Parse coverage percentage from pytest coverage JSON output."""
    path = Path(coverage_file)
    if not path.exists():
        return 0.0
    try:
        data   = json.loads(path.read_text())
        totals = data.get("totals", {})
        return round(totals.get("percent_covered", 0.0), 1)
    except (json.JSONDecodeError, KeyError):
        return 0.0


def parse_jest_coverage() -> float:
    """Parse coverage percentage from Jest coverage-summary.json."""
    path = Path("coverage/coverage-summary.json")
    if not path.exists():
        return 0.0
    try:
        data  = json.loads(path.read_text())
        total = data.get("total", {})
        lines = total.get("lines", {})
        return round(lines.get("pct", 0.0), 1)
    except (json.JSONDecodeError, KeyError):
        return 0.0


# ── Main runner ───────────────────────────────────────────────────────────────

def main():
    detected_services = json.loads(DETECTED_SERVICES)

    if not detected_services:
        print("No services detected. Skipping test execution.")
        with open(GITHUB_OUTPUT, "a") as f:
            f.write("tests_passed=0\n")
            f.write("tests_failed=0\n")
            f.write("coverage_percentage=0\n")
            f.write("test_report={}\n")
        sys.exit(0)

    if not Path(TEST_OUTPUT_DIR).exists():
        print(f"Test output directory {TEST_OUTPUT_DIR} not found. Skipping.")
        with open(GITHUB_OUTPUT, "a") as f:
            f.write("tests_passed=0\n")
            f.write("tests_failed=0\n")
            f.write("coverage_percentage=0\n")
            f.write("test_report={}\n")
        sys.exit(0)

    print(f"\nRunning generated tests in: {TEST_OUTPUT_DIR}")
    print(f"Services: {detected_services}")
    print(f"Coverage threshold: {COVERAGE_THRESHOLD}%\n")

    full_report = {
        "services": {},
        "total_passed":   0,
        "total_failed":   0,
        "total_tests":    0,
        "overall_coverage": 0.0,
    }

    all_passed = 0
    all_failed = 0
    coverage_values = []

    service_test_dir_map = {
        "fastapi": TEST_OUTPUT_DIR,
        "nextjs":  TEST_OUTPUT_DIR,
        "node":    TEST_OUTPUT_DIR,
    }

    for service in detected_services:
        test_dir = service_test_dir_map.get(service, TEST_OUTPUT_DIR)

        print(f"── Running {service.upper()} tests ────────────────────────────────")

        if service == "fastapi":
            result = run_pytest(test_dir)
        elif service in ("nextjs", "node"):
            result = run_jest(test_dir, service)
        else:
            print(f"Unknown service: {service}. Skipping.")
            continue

        all_passed += result.get("passed", 0)
        all_failed += result.get("failed", 0)

        cov = result.get("coverage", 0.0)
        if cov > 0:
            coverage_values.append(cov)

        full_report["services"][service] = result

        print(f"\n  Results: {result.get('passed', 0)} passed | {result.get('failed', 0)} failed")
        print(f"  Coverage: {cov}%\n")

    full_report["total_passed"] = all_passed
    full_report["total_failed"] = all_failed
    full_report["total_tests"]  = all_passed + all_failed
    full_report["overall_coverage"] = (
        round(sum(coverage_values) / len(coverage_values), 1)
        if coverage_values else 0.0
    )

    # Final summary
    print("── Test Run Summary ───────────────────────────────────")
    print(f"  Total passed:  {all_passed}")
    print(f"  Total failed:  {all_failed}")
    print(f"  Total tests:   {all_passed + all_failed}")
    print(f"  Coverage:      {full_report['overall_coverage']}%")
    print(f"  Threshold:     {COVERAGE_THRESHOLD}%")

    # Write GitHub outputs
    report_json = json.dumps(full_report)

    with open(GITHUB_OUTPUT, "a") as f:
        f.write(f"tests_passed={all_passed}\n")
        f.write(f"tests_failed={all_failed}\n")
        f.write(f"coverage_percentage={full_report['overall_coverage']}\n")
        f.write(f"test_report={report_json}\n")

    # Determine exit code
    should_fail = False

    if FAIL_ON_TEST_FAILURE and all_failed > 0:
        print(f"\nFAIL: {all_failed} test case(s) failed.")
        should_fail = True

    if full_report["overall_coverage"] < COVERAGE_THRESHOLD:
        print(
            f"\nFAIL: Coverage {full_report['overall_coverage']}% "
            f"is below the required {COVERAGE_THRESHOLD}%."
        )
        should_fail = True

    if should_fail:
        sys.exit(1)

    print(f"\nPASS: All tests passed with {full_report['overall_coverage']}% coverage.")


if __name__ == "__main__":
    main()
