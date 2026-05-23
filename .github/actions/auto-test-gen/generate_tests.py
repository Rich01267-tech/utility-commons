#!/usr/bin/env python3
"""
generate_tests.py — OpenAI Codex Test Generation Engine
=========================================================
Reads the structured diff output from parse_diff.py, loads the
correct prompt template per service type, calls the OpenAI API
to generate test cases, and writes the generated tests to the
output directory.

Supports Next.js (Jest + RTL), Node/Express (Jest + Supertest),
and FastAPI (Pytest + httpx).
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from openai import OpenAI


# ── Environment variables ─────────────────────────────────────────────────────

OPENAI_API_KEY    = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL      = os.environ.get("OPENAI_MODEL", "gpt-4.1")
MAX_TOKENS        = int(os.environ.get("MAX_TOKENS", "4000"))
DIFF_OUTPUT       = os.environ.get("DIFF_OUTPUT", "")
DETECTED_SERVICES = os.environ.get("DETECTED_SERVICES", "[]")
ACTION_PATH       = os.environ.get("ACTION_PATH", ".")
TEST_OUTPUT_DIR   = os.environ.get("TEST_OUTPUT_DIR", "__generated_tests__")
GITHUB_OUTPUT     = os.environ.get("GITHUB_OUTPUT", "/dev/stdout")

# Initialise OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# ── Prompt loader ─────────────────────────────────────────────────────────────

def load_prompt(service: str) -> str:
    """Load the test generation prompt template for a given service."""
    prompt_map = {
        "nextjs":  "nextjs_test_prompt.md",
        "node":    "node_test_prompt.md",
        "fastapi": "fastapi_test_prompt.md",
    }
    filename = prompt_map.get(service)
    if not filename:
        raise ValueError(f"Unknown service type: {service}")

    # Look in prompts/ relative to action path
    prompt_path = Path(ACTION_PATH) / ".." / ".." / ".." / "prompts" / filename
    prompt_path = prompt_path.resolve()

    # Fallback — look in same directory as this script
    if not prompt_path.exists():
        prompt_path = Path(ACTION_PATH) / filename

    if not prompt_path.exists():
        print(f"Warning: Prompt file not found at {prompt_path}. Using built-in fallback.")
        return get_fallback_prompt(service)

    return prompt_path.read_text(encoding="utf-8")


def get_fallback_prompt(service: str) -> str:
    """Built-in fallback prompt if external prompt file is not found."""
    base = """You are an expert test engineer. Generate comprehensive test cases for the provided code changes.

For each changed function or component generate:
1. Unit tests — test the function in isolation with valid inputs
2. Edge case tests — boundary values, empty inputs, large inputs
3. Negative tests — invalid inputs, error conditions, unauthorised access
4. Integration tests — how this function interacts with its dependencies
5. Security tests — injection attempts, auth bypass, data validation failures

Return ONLY the test file content. No explanation. No markdown fences. Just the raw test code.
"""
    service_additions = {
        "nextjs": "Use Jest and React Testing Library. Follow Next.js App Router patterns. Test Server and Client Components appropriately.",
        "node":   "Use Jest and Supertest. Test Express routes, middleware, and controllers. Include auth token fixtures.",
        "fastapi":"Use Pytest and httpx.AsyncClient. Test FastAPI endpoints with async patterns. Include auth header fixtures.",
    }
    return base + "\n" + service_additions.get(service, "")


# ── Test file naming ──────────────────────────────────────────────────────────

def get_test_file_path(source_path: str, service: str, output_dir: str) -> str:
    """
    Generate the output test file path based on the source file path.
    Mirrors the source structure inside the output directory.
    """
    path = Path(source_path)
    stem = path.stem
    suffix = path.suffix

    if service == "fastapi":
        test_filename = f"test_{stem}.py"
    elif service in ("nextjs", "node"):
        if suffix in (".tsx", ".jsx"):
            test_filename = f"{stem}.test.tsx"
        else:
            test_filename = f"{stem}.test.ts"
    else:
        test_filename = f"{stem}.test{suffix}"

    # Mirror directory structure inside output dir
    relative_dir = path.parent
    output_path  = Path(output_dir) / relative_dir / test_filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    return str(output_path)


# ── OpenAI API call ───────────────────────────────────────────────────────────

def call_openai(system_prompt: str, user_message: str, retries: int = 3) -> str:
    """Call the OpenAI API with retry logic on rate limit errors."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                max_tokens=MAX_TOKENS,
                temperature=0.2,        # low temperature for deterministic test code
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ]
            )
            return response.choices[0].message.content or ""

        except Exception as e:
            error_str = str(e).lower()
            if "rate_limit" in error_str or "429" in error_str:
                wait = 2 ** attempt * 5   # 5s, 10s, 20s
                print(f"Rate limited. Retrying in {wait}s... (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
            elif "context_length" in error_str or "maximum" in error_str:
                print(f"Context too long for {OPENAI_MODEL}. Truncating and retrying...")
                # Truncate the user message and retry
                user_message = user_message[:int(len(user_message) * 0.7)]
            else:
                print(f"OpenAI API error: {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(3)

    raise RuntimeError(f"Failed to get response from OpenAI after {retries} attempts.")


# ── Test generation per file ──────────────────────────────────────────────────

def build_user_message(file_entry: dict, service: str) -> str:
    """
    Build the user message to send to OpenAI for a specific file.
    Includes file path, changed functions, and the diff additions.
    """
    file_path         = file_entry["path"]
    changed_functions = file_entry.get("changed_functions", [])
    patch_additions   = file_entry.get("patch_additions", "")
    status            = file_entry.get("status", "modified")

    function_names = (
        ", ".join(f["name"] for f in changed_functions)
        if changed_functions else "unknown (full file change)"
    )

    message = f"""FILE: {file_path}
STATUS: {status}
SERVICE: {service}
CHANGED FUNCTIONS: {function_names}

CODE CHANGES (additions only):
{patch_additions[:6000]}

Generate complete test cases covering all changed functions listed above.
Test file should be immediately runnable with no modifications.
"""

    if changed_functions:
        message += "\n\nFUNCTION SIGNATURES DETECTED:\n"
        for func in changed_functions:
            message += f"  - {func.get('signature', func['name'])}\n"

    return message


def generate_tests_for_file(
    file_entry: dict,
    service: str,
    system_prompt: str,
    output_dir: str,
) -> dict:
    """
    Generate test cases for a single changed file.
    Returns a result dict with status, path, and test count.
    """
    file_path = file_entry["path"]
    print(f"  Generating tests for: {file_path}")

    try:
        user_message  = build_user_message(file_entry, service)
        test_content  = call_openai(system_prompt, user_message)

        # Strip any markdown fences if model added them anyway
        test_content  = re.sub(r"^```[\w]*\n?", "", test_content, flags=re.MULTILINE)
        test_content  = re.sub(r"\n?```$",       "", test_content, flags=re.MULTILINE)
        test_content  = test_content.strip()

        if not test_content:
            return {"path": file_path, "status": "empty", "test_count": 0, "output_path": None}

        # Count test cases in generated output
        if service == "fastapi":
            test_count = len(re.findall(r"^def test_|^async def test_", test_content, re.MULTILINE))
        else:
            test_count = len(re.findall(r"\bit\(|\btest\(|\bdescribe\(", test_content))

        # Write test file
        output_path = get_test_file_path(file_path, service, output_dir)
        Path(output_path).write_text(test_content, encoding="utf-8")

        print(f"    Generated {test_count} test case(s) → {output_path}")

        return {
            "path":        file_path,
            "status":      "success",
            "test_count":  test_count,
            "output_path": output_path,
            "service":     service,
            "functions":   [f["name"] for f in file_entry.get("changed_functions", [])],
        }

    except Exception as e:
        print(f"    Error generating tests for {file_path}: {e}")
        return {"path": file_path, "status": "error", "error": str(e), "test_count": 0}


# ── Main generation logic ─────────────────────────────────────────────────────

def main():
    if not DIFF_OUTPUT:
        print("No diff output received from parse step. Nothing to generate.")
        with open(GITHUB_OUTPUT, "a") as f:
            f.write("tests_generated=0\n")
            f.write("generation_report={}\n")
        sys.exit(0)

    # Parse diff data
    try:
        diff_data = json.loads(DIFF_OUTPUT)
    except json.JSONDecodeError as e:
        print(f"Failed to parse diff output JSON: {e}")
        sys.exit(1)

    detected_services = json.loads(DETECTED_SERVICES)

    if not detected_services:
        print("No services detected. Skipping test generation.")
        with open(GITHUB_OUTPUT, "a") as f:
            f.write("tests_generated=0\n")
        sys.exit(0)

    # Create output directory
    Path(TEST_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    print(f"\nGenerating tests for services: {detected_services}")
    print(f"Model: {OPENAI_MODEL} | Max tokens: {MAX_TOKENS}")
    print(f"Output directory: {TEST_OUTPUT_DIR}\n")

    generation_report = {
        "services": {},
        "total_tests_generated": 0,
        "total_files_processed": 0,
        "errors": [],
    }

    total_tests = 0

    for service in detected_services:
        service_data = diff_data.get("services_detected", {}).get(service)
        if not service_data:
            continue

        framework = service_data["framework"]
        files     = service_data["files"]

        print(f"── {framework} ({len(files)} file(s)) ──────────────────────────")

        # Load prompt for this service
        system_prompt = load_prompt(service)

        service_results = []
        service_tests   = 0

        for file_entry in files:
            result = generate_tests_for_file(
                file_entry, service, system_prompt, TEST_OUTPUT_DIR
            )
            service_results.append(result)
            service_tests += result.get("test_count", 0)

            if result["status"] == "error":
                generation_report["errors"].append(result)

            # Small delay between API calls to avoid rate limiting
            time.sleep(0.5)

        total_tests += service_tests
        generation_report["total_files_processed"] += len(files)
        generation_report["services"][service] = {
            "framework":     framework,
            "test_framework": service_data["test_framework"],
            "files_processed": len(files),
            "tests_generated": service_tests,
            "results":       service_results,
        }

        print(f"  Total tests generated for {framework}: {service_tests}\n")

    generation_report["total_tests_generated"] = total_tests

    # Summary
    print("── Generation Summary ─────────────────────────────────")
    print(f"  Total test cases generated: {total_tests}")
    print(f"  Total files processed:      {generation_report['total_files_processed']}")
    print(f"  Errors:                     {len(generation_report['errors'])}")

    if generation_report["errors"]:
        print("\n  Errors encountered:")
        for err in generation_report["errors"]:
            print(f"    - {err['path']}: {err.get('error', 'unknown error')}")

    # Write outputs
    report_json = json.dumps(generation_report)

    with open(GITHUB_OUTPUT, "a") as f:
        f.write(f"tests_generated={total_tests}\n")
        f.write(f"generation_report={report_json}\n")

    if total_tests == 0:
        print("\nWarning: No test cases were generated.")
        sys.exit(0)

    print(f"\nTest generation complete. {total_tests} test case(s) written to {TEST_OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
