#!/usr/bin/env python3
"""
post_comment.py — PR Comment Formatter and Poster
==================================================
Formats the test generation and execution results into a clean,
structured GitHub PR comment and posts it using the GitHub API.

The comment shows:
  - Summary: total tests generated, passed, failed, coverage %
  - Per-service breakdown with function-level detail
  - Per-test case pass/fail status
  - Coverage percentage vs threshold
  - Clear PASS / FAIL status at the top

Also handles updating an existing bot comment on re-runs so
the PR is not flooded with duplicate comments.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone


# ── Environment variables ─────────────────────────────────────────────────────

GITHUB_TOKEN        = os.environ["GITHUB_TOKEN"]
PR_NUMBER           = os.environ["PR_NUMBER"]
REPO_FULL_NAME      = os.environ["REPO_FULL_NAME"]
TESTS_GENERATED     = int(os.environ.get("TESTS_GENERATED", "0"))
TESTS_PASSED        = int(os.environ.get("TESTS_PASSED", "0"))
TESTS_FAILED        = int(os.environ.get("TESTS_FAILED", "0"))
COVERAGE_PERCENTAGE = float(os.environ.get("COVERAGE_PERCENTAGE", "0"))
COVERAGE_THRESHOLD  = float(os.environ.get("COVERAGE_THRESHOLD", "80"))
TEST_REPORT         = os.environ.get("TEST_REPORT", "{}")
OUTPUT_MODE         = os.environ.get("OUTPUT_MODE", "comment")
GITHUB_OUTPUT       = os.environ.get("GITHUB_OUTPUT", "/dev/stdout")

# Bot comment identifier — used to find and update existing comments
BOT_COMMENT_MARKER = "<!-- auto-test-gen-report -->"


# ── GitHub API helpers ────────────────────────────────────────────────────────

def github_request(
    url: str,
    method: str = "GET",
    data: dict | None = None,
    accept: str = "application/vnd.github.v3+json",
) -> dict | list | None:
    """Make an authenticated GitHub API request."""
    body = json.dumps(data).encode("utf-8") if data else None
    req  = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization":  f"Bearer {GITHUB_TOKEN}",
            "Accept":          accept,
            "Content-Type":   "application/json",
            "User-Agent":     "auto-test-gen-action/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"GitHub API error {e.code}: {e.reason}")
        print(f"Response body: {body[:500]}")
        return None


def get_existing_bot_comment() -> dict | None:
    """Find an existing auto-test-gen comment on this PR to update instead of creating new."""
    url      = f"https://api.github.com/repos/{REPO_FULL_NAME}/issues/{PR_NUMBER}/comments"
    comments = github_request(url)
    if not isinstance(comments, list):
        return None
    for comment in comments:
        if BOT_COMMENT_MARKER in comment.get("body", ""):
            return comment
    return None


def post_comment(body: str) -> str | None:
    """Post or update the PR comment. Returns the comment URL."""
    existing = get_existing_bot_comment()

    if existing:
        # Update existing comment
        comment_id = existing["id"]
        url        = f"https://api.github.com/repos/{REPO_FULL_NAME}/issues/comments/{comment_id}"
        result     = github_request(url, method="PATCH", data={"body": body})
        if result:
            print(f"Updated existing PR comment: {result.get('html_url')}")
            return result.get("html_url")
    else:
        # Create new comment
        url    = f"https://api.github.com/repos/{REPO_FULL_NAME}/issues/{PR_NUMBER}/comments"
        result = github_request(url, method="POST", data={"body": body})
        if result:
            print(f"Posted new PR comment: {result.get('html_url')}")
            return result.get("html_url")

    return None


# ── Comment formatters ────────────────────────────────────────────────────────

def format_status_badge(passed: bool) -> str:
    return "✅ PASS" if passed else "❌ FAIL"


def format_coverage_badge(coverage: float, threshold: float) -> str:
    if coverage >= threshold:
        return f"✅ {coverage}%"
    else:
        return f"❌ {coverage}% (below {threshold}% threshold)"


def format_test_outcome(outcome: str) -> str:
    icons = {
        "passed": "✅",
        "failed": "❌",
        "error":  "⚠️",
        "skipped":"⏭️",
    }
    return icons.get(outcome.lower(), "❓")


def truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def format_pr_comment(report: dict) -> str:
    """
    Build the full PR comment body with all test results,
    coverage data, and per-service breakdowns.
    """
    overall_passed  = TESTS_FAILED == 0
    coverage_ok     = COVERAGE_PERCENTAGE >= COVERAGE_THRESHOLD
    overall_ok      = overall_passed and coverage_ok

    timestamp       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Header ────────────────────────────────────────────────────────────────
    lines = [
        BOT_COMMENT_MARKER,
        "",
        f"## {'✅' if overall_ok else '❌'} Auto Test Generation Report",
        "",
        f"> Generated by [auto-test-gen](https://github.com/{REPO_FULL_NAME}) · {timestamp}",
        "",
    ]

    # ── Summary table ─────────────────────────────────────────────────────────
    lines += [
        "### Summary",
        "",
        "| Metric | Value | Status |",
        "|--------|-------|--------|",
        f"| Tests Generated | {TESTS_GENERATED} | ℹ️ |",
        f"| Tests Passed    | {TESTS_PASSED} | {'✅' if TESTS_PASSED > 0 else 'ℹ️'} |",
        f"| Tests Failed    | {TESTS_FAILED} | {'❌' if TESTS_FAILED > 0 else '✅'} |",
        f"| Coverage        | {COVERAGE_PERCENTAGE}% | {format_coverage_badge(COVERAGE_PERCENTAGE, COVERAGE_THRESHOLD)} |",
        f"| Overall Status  | — | {format_status_badge(overall_ok)} |",
        "",
    ]

    # ── Per-service breakdown ─────────────────────────────────────────────────
    services = report.get("services", {})

    if not services:
        lines += [
            "### No testable changes detected",
            "",
            "No functions or components were changed in this PR that required test generation.",
            "",
        ]
    else:
        lines.append("### Service Breakdown")
        lines.append("")

        service_labels = {
            "nextjs":  "Next.js Frontend",
            "node":    "Node / Express Backend",
            "fastapi": "FastAPI Backend",
        }

        for service, service_data in services.items():
            label     = service_labels.get(service, service.upper())
            s_passed  = service_data.get("passed", 0)
            s_failed  = service_data.get("failed", 0)
            s_total   = service_data.get("total", 0)
            s_coverage= service_data.get("coverage", 0.0)
            s_status  = service_data.get("status", "completed")
            tests     = service_data.get("tests", [])

            service_ok = s_failed == 0 and s_coverage >= COVERAGE_THRESHOLD

            lines += [
                f"<details>",
                f"<summary>{'✅' if service_ok else '❌'} <strong>{label}</strong> "
                f"— {s_passed}/{s_total} passed · Coverage: {s_coverage}%</summary>",
                "",
            ]

            if s_status == "no_tests":
                lines.append("> No test files found for this service.")
                lines.append("")
            elif not tests:
                lines.append("> Test results unavailable.")
                lines.append("")
            else:
                # Per-test case table
                lines += [
                    "| # | Test Case | Outcome | Duration |",
                    "|---|-----------|---------|----------|",
                ]

                for i, test in enumerate(tests, 1):
                    name     = truncate(test.get("name", "unknown"), 80)
                    outcome  = test.get("outcome", "unknown")
                    duration = test.get("duration", 0)
                    icon     = format_test_outcome(outcome)

                    lines.append(
                        f"| {i} | `{name}` | {icon} {outcome} | {duration}s |"
                    )

                lines.append("")

                # Show failure details
                failed_tests = [t for t in tests if not t.get("passed", True)]
                if failed_tests:
                    lines.append("**Failure Details:**")
                    lines.append("")
                    for test in failed_tests:
                        name   = test.get("name", "unknown")
                        reason = test.get("failure_reason", "No details available")
                        lines += [
                            f"<details>",
                            f"<summary>❌ <code>{truncate(name, 60)}</code></summary>",
                            "",
                            "```",
                            truncate(reason, 500),
                            "```",
                            "",
                            "</details>",
                            "",
                        ]

            lines.append("</details>")
            lines.append("")

    # ── Coverage details ──────────────────────────────────────────────────────
    lines += [
        "### Coverage",
        "",
        f"| Required | Actual | Status |",
        f"|----------|--------|--------|",
        f"| {COVERAGE_THRESHOLD}% | {COVERAGE_PERCENTAGE}% | "
        f"{format_coverage_badge(COVERAGE_PERCENTAGE, COVERAGE_THRESHOLD)} |",
        "",
    ]

    if COVERAGE_PERCENTAGE < COVERAGE_THRESHOLD:
        lines += [
            "> ⚠️ **Coverage is below the required threshold.**",
            "> Add more test coverage or lower the threshold in the workflow configuration.",
            "",
        ]

    # ── Action required section ───────────────────────────────────────────────
    if not overall_ok:
        lines += [
            "---",
            "",
            "### ❌ Action Required",
            "",
        ]
        if TESTS_FAILED > 0:
            lines += [
                f"- **{TESTS_FAILED} test case(s) failed.** Review the failure details above and fix the issues before merging.",
            ]
        if not coverage_ok:
            lines += [
                f"- **Coverage {COVERAGE_PERCENTAGE}% is below the {COVERAGE_THRESHOLD}% threshold.** "
                f"Increase test coverage before merging.",
            ]
        lines.append("")
    else:
        lines += [
            "---",
            "",
            "### ✅ All checks passed",
            "",
            f"All {TESTS_GENERATED} generated test cases passed and coverage meets the {COVERAGE_THRESHOLD}% threshold.",
            "This PR is ready to merge from an automated test perspective.",
            "",
        ]

    # ── Footer ────────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "<sub>🤖 Generated automatically by "
        "[auto-test-gen](https://github.com/marketplace/actions) "
        f"on every PR · Powered by OpenAI · Report ID: {PR_NUMBER}-{timestamp.replace(' ', '-')}</sub>",
        "",
    ]

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Formatting and posting test report for PR #{PR_NUMBER}...")
    print(f"Results: {TESTS_PASSED} passed | {TESTS_FAILED} failed | Coverage: {COVERAGE_PERCENTAGE}%")

    # Parse test report
    try:
        report = json.loads(TEST_REPORT) if TEST_REPORT else {}
    except json.JSONDecodeError:
        report = {}

    # Build comment body
    comment_body = format_pr_comment(report)

    # Post or skip based on output mode
    comment_url = None

    if OUTPUT_MODE in ("comment", "both"):
        comment_url = post_comment(comment_body)
        if not comment_url:
            print("Warning: Failed to post PR comment. Continuing without comment.")
    else:
        print(f"Output mode is '{OUTPUT_MODE}' — skipping PR comment.")

    # Write outputs
    with open(GITHUB_OUTPUT, "a") as f:
        f.write(f"report_url={comment_url or ''}\n")

    print("PR comment step complete.")


if __name__ == "__main__":
    main()
