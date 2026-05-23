#!/usr/bin/env python3
"""
parse_diff.py — PR Diff Parser and Service Detector
====================================================
Fetches the PR diff from GitHub, identifies changed files,
detects which service type(s) are affected (Next.js, Node/Express,
FastAPI), and outputs structured data for the test generation step.

Supports both monorepo and individual repo setups.
"""

import os
import sys
import json
import re
import urllib.request
import urllib.error


# ── Environment variables ─────────────────────────────────────────────────────

GITHUB_TOKEN      = os.environ["GITHUB_TOKEN"]
PR_NUMBER         = os.environ["PR_NUMBER"]
REPO_FULL_NAME    = os.environ["REPO_FULL_NAME"]
SERVICE_TYPE      = os.environ.get("SERVICE_TYPE", "auto")
REPO_TYPE         = os.environ.get("REPO_TYPE", "individual")
MONOREPO_SERVICES = os.environ.get("MONOREPO_SERVICES", "")
GITHUB_OUTPUT     = os.environ.get("GITHUB_OUTPUT", "/dev/stdout")


# ── Service detection patterns ────────────────────────────────────────────────

SERVICE_PATTERNS = {
    "nextjs": {
        "file_patterns": [
            r"\.tsx?$",
            r"\.jsx?$",
            r"next\.config\.",
            r"app/.*page\.",
            r"components/",
            r"pages/",
            r"tailwind\.config\.",
            r"__tests__/.*\.(tsx?|jsx?)$",
        ],
        "content_patterns": [
            r"from ['\"]react['\"]",
            r"from ['\"]next/",
            r"export default function",
            r"useState|useEffect|useCallback",
        ],
        "framework": "Next.js",
        "test_framework": "jest",
    },
    "node": {
        "file_patterns": [
            r"\.js$",
            r"\.ts$",
            r"routes/",
            r"controllers/",
            r"middleware/",
            r"models/.*\.(js|ts)$",
            r"package\.json$",
        ],
        "content_patterns": [
            r"require\(['\"]express['\"]",
            r"from ['\"]express['\"]",
            r"router\.(get|post|put|delete|patch)",
            r"mongoose\.model",
            r"app\.use\(",
        ],
        "framework": "Node/Express",
        "test_framework": "jest",
    },
    "fastapi": {
        "file_patterns": [
            r"\.py$",
            r"routers/",
            r"schemas/",
            r"models/.*\.py$",
            r"dependencies/",
            r"tests/.*\.py$",
        ],
        "content_patterns": [
            r"from fastapi",
            r"@router\.(get|post|put|delete|patch)",
            r"@app\.(get|post|put|delete|patch)",
            r"BaseModel",
            r"Depends\(",
            r"async def ",
        ],
        "framework": "FastAPI",
        "test_framework": "pytest",
    },
}


# ── GitHub API helpers ────────────────────────────────────────────────────────

def github_request(url: str, accept: str = "application/vnd.github.v3+json") -> bytes:
    """Make an authenticated GitHub API request."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": accept,
            "User-Agent": "auto-test-gen-action/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        print(f"GitHub API error {e.code}: {e.reason} for URL: {url}")
        sys.exit(1)


def fetch_pr_files() -> list[dict]:
    """Fetch the list of files changed in the PR."""
    url = f"https://api.github.com/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}/files"
    data = github_request(url)
    return json.loads(data)


def fetch_file_content(file_path: str, ref: str) -> str:
    """Fetch the raw content of a file at a specific git ref."""
    url = f"https://raw.githubusercontent.com/{REPO_FULL_NAME}/{ref}/{file_path}"
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
        )
        with urllib.request.urlopen(req) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return ""


def fetch_pr_head_sha() -> str:
    """Get the head commit SHA of the PR."""
    url = f"https://api.github.com/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}"
    data = github_request(url)
    pr_data = json.loads(data)
    return pr_data["head"]["sha"]


# ── Service detection ─────────────────────────────────────────────────────────

def detect_service_from_file(file_path: str, patch: str) -> set[str]:
    """Detect which service(s) a file belongs to based on path and content."""
    detected = set()

    for service, patterns in SERVICE_PATTERNS.items():
        # Check file path patterns
        for pattern in patterns["file_patterns"]:
            if re.search(pattern, file_path, re.IGNORECASE):
                detected.add(service)
                break

        # Check content patterns in the patch diff
        if patch:
            for pattern in patterns["content_patterns"]:
                if re.search(pattern, patch, re.MULTILINE):
                    detected.add(service)
                    break

    return detected


def detect_monorepo_service(file_path: str, service_dirs: list[str]) -> str | None:
    """For monorepos, detect which service directory a file belongs to."""
    for service_dir in service_dirs:
        if file_path.startswith(service_dir.strip() + "/"):
            return service_dir.strip()
    return None


# ── Diff parsing ──────────────────────────────────────────────────────────────

def extract_changed_functions(patch: str, file_path: str) -> list[dict]:
    """
    Extract the names and content of changed functions from a diff patch.
    Returns a list of dicts with function name, content, and line numbers.
    """
    if not patch:
        return []

    changed_functions = []

    # Python function detection
    if file_path.endswith(".py"):
        func_pattern = re.compile(
            r"^\+\s*(async\s+)?def\s+(\w+)\s*\(([^)]*)\)",
            re.MULTILINE
        )
        for match in func_pattern.finditer(patch):
            changed_functions.append({
                "name": match.group(2),
                "signature": match.group(0).lstrip("+").strip(),
                "is_async": bool(match.group(1)),
                "language": "python",
            })

    # TypeScript/JavaScript function detection
    elif file_path.endswith((".ts", ".tsx", ".js", ".jsx")):
        patterns = [
            # Arrow functions: const myFunc = () => {}
            re.compile(r"^\+\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(", re.MULTILINE),
            # Named functions: function myFunc() {}
            re.compile(r"^\+\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE),
            # Class methods
            re.compile(r"^\+\s*(?:async\s+)?(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{", re.MULTILINE),
            # React components
            re.compile(r"^\+\s*(?:export\s+default\s+)?(?:function|const)\s+([A-Z]\w+)", re.MULTILINE),
        ]
        for pattern in patterns:
            for match in pattern.finditer(patch):
                func_name = match.group(1)
                if func_name and func_name not in [f["name"] for f in changed_functions]:
                    changed_functions.append({
                        "name": func_name,
                        "signature": match.group(0).lstrip("+").strip(),
                        "is_async": "async" in match.group(0),
                        "language": "typescript" if file_path.endswith((".ts", ".tsx")) else "javascript",
                    })

    return changed_functions


def parse_patch_additions(patch: str) -> str:
    """Extract only the added lines from a diff patch."""
    if not patch:
        return ""
    lines = []
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])  # strip the leading +
    return "\n".join(lines)


# ── Main parsing logic ────────────────────────────────────────────────────────

def main():
    print(f"Fetching PR #{PR_NUMBER} diff from {REPO_FULL_NAME}...")

    pr_files = fetch_pr_files()
    head_sha = fetch_pr_head_sha()

    print(f"Found {len(pr_files)} changed file(s). Head SHA: {head_sha[:8]}")

    # Parse monorepo service directories
    monorepo_service_dirs = (
        [s.strip() for s in MONOREPO_SERVICES.split(",") if s.strip()]
        if REPO_TYPE == "monorepo" else []
    )

    # Build structured diff output
    diff_data: dict = {
        "pr_number": PR_NUMBER,
        "repo": REPO_FULL_NAME,
        "head_sha": head_sha,
        "repo_type": REPO_TYPE,
        "files": [],
        "services_detected": {},
        "total_additions": 0,
        "total_deletions": 0,
    }

    service_files: dict[str, list] = {
        "nextjs": [],
        "node": [],
        "fastapi": [],
    }

    skipped_files = []
    skip_patterns = [
        r"\.lock$",
        r"\.min\.js$",
        r"node_modules/",
        r"\.next/",
        r"dist/",
        r"build/",
        r"__pycache__/",
        r"\.pyc$",
        r"coverage/",
        r"\.generated\.",
        r"migrations/",
        r"\.env",
    ]

    for pr_file in pr_files:
        file_path = pr_file["filename"]
        status    = pr_file["status"]           # added, modified, removed, renamed
        additions = pr_file.get("additions", 0)
        deletions = pr_file.get("deletions", 0)
        patch     = pr_file.get("patch", "")

        # Skip irrelevant files
        should_skip = any(re.search(p, file_path) for p in skip_patterns)
        if should_skip or status == "removed" or additions == 0:
            skipped_files.append(file_path)
            continue

        diff_data["total_additions"] += additions
        diff_data["total_deletions"] += deletions

        # Determine which service this file belongs to
        if SERVICE_TYPE != "auto":
            # Explicit service type set by caller
            detected_services = {SERVICE_TYPE}
        elif REPO_TYPE == "monorepo":
            service_dir = detect_monorepo_service(file_path, monorepo_service_dirs)
            if service_dir:
                detected_services = detect_service_from_file(file_path, patch)
            else:
                detected_services = detect_service_from_file(file_path, patch)
        else:
            detected_services = detect_service_from_file(file_path, patch)

        if not detected_services:
            skipped_files.append(file_path)
            continue

        # Extract changed functions
        changed_functions = extract_changed_functions(patch, file_path)
        additions_only    = parse_patch_additions(patch)

        file_entry = {
            "path":              file_path,
            "status":            status,
            "additions":         additions,
            "deletions":         deletions,
            "services":          list(detected_services),
            "changed_functions": changed_functions,
            "patch_additions":   additions_only,
            "full_patch":        patch,
        }

        diff_data["files"].append(file_entry)

        # Group files by service
        for service in detected_services:
            if service in service_files:
                service_files[service].append(file_entry)

    # Build services summary
    for service, files in service_files.items():
        if files:
            total_functions = sum(len(f["changed_functions"]) for f in files)
            diff_data["services_detected"][service] = {
                "framework":        SERVICE_PATTERNS[service]["framework"],
                "test_framework":   SERVICE_PATTERNS[service]["test_framework"],
                "file_count":       len(files),
                "function_count":   total_functions,
                "files":            files,
            }

    # Summary output
    print("\n── Diff Parse Summary ─────────────────────────────────")
    print(f"  Files analysed:  {len(diff_data['files'])}")
    print(f"  Files skipped:   {len(skipped_files)}")
    print(f"  Total additions: {diff_data['total_additions']} lines")
    print(f"  Total deletions: {diff_data['total_deletions']} lines")
    print(f"  Services found:  {list(diff_data['services_detected'].keys()) or 'none'}")

    for service, data in diff_data["services_detected"].items():
        print(f"\n  [{service.upper()}] {data['framework']}")
        print(f"    Files:     {data['file_count']}")
        print(f"    Functions: {data['function_count']}")

    if not diff_data["services_detected"]:
        print("\nNo testable changes detected in this PR. Skipping test generation.")
        # Write empty outputs and exit cleanly
        with open(GITHUB_OUTPUT, "a") as f:
            f.write("diff_output=\n")
            f.write("detected_services=\n")
            f.write("has_changes=false\n")
        sys.exit(0)

    # Write outputs for next steps
    diff_json         = json.dumps(diff_data)
    detected_services = json.dumps(list(diff_data["services_detected"].keys()))

    with open(GITHUB_OUTPUT, "a") as f:
        f.write(f"diff_output={diff_json}\n")
        f.write(f"detected_services={detected_services}\n")
        f.write("has_changes=true\n")

    print("\nDiff parsing complete. Passing data to test generation step.")


if __name__ == "__main__":
    main()
