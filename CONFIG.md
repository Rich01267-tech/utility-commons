# Auto Test Generation — Configuration Reference

## Overview

This document covers every configurable input, environment variable,
and setting available in the auto-test-gen composite action. Use this
as a reference when customising the system for individual repos or
adjusting behaviour across the platform.

---

## Composite Action Inputs

These inputs are passed to the composite action from each app repo's
workflow file under the `with:` block.

### Required Inputs

| Input | Type | Description |
|---|---|---|
| `openai_api_key` | string | OpenAI API key for test generation. Store as a GitHub Secret — never hardcode. |
| `github_token` | string | GitHub token for reading PR diff and posting comments. Use `${{ secrets.GITHUB_TOKEN }}` — auto-provided. |

### Service Configuration

| Input | Type | Default | Options | Description |
|---|---|---|---|---|
| `service_type` | string | `auto` | `auto` `nextjs` `node` `fastapi` | Service type to generate tests for. Use `auto` to detect from file content and path. Set explicitly if auto-detection is unreliable for your repo structure. |
| `repo_type` | string | `individual` | `individual` `monorepo` | Whether this repo is a standalone service or a monorepo containing multiple services. |
| `monorepo_services` | string | `""` | Comma-separated list | Required when `repo_type` is `monorepo`. List the service directory names. Example: `"frontend,backend,api"` |

### Test Behaviour

| Input | Type | Default | Description |
|---|---|---|---|
| `coverage_threshold` | string | `"80"` | Minimum coverage percentage required to pass. PR fails if overall coverage drops below this value. Accepts any integer between 0 and 100. |
| `fail_on_test_failure` | string | `"true"` | Set to `"false"` to allow PRs to merge even if generated tests fail. Not recommended for production branches. |
| `output_mode` | string | `"comment"` | How test results are delivered. See Output Modes below. |
| `test_output_dir` | string | `"__generated_tests__"` | Directory where generated test files are written. Change if this conflicts with an existing directory in your repo. |

### OpenAI Configuration

| Input | Type | Default | Description |
|---|---|---|---|
| `openai_model` | string | `"gpt-4.1"` | OpenAI model used for test generation. See Model Selection below. |
| `max_tokens` | string | `"4000"` | Maximum tokens per OpenAI API call. Increase for complex files with many functions. Decrease to reduce costs. |

---

## Output Modes

Configure `output_mode` to control how test results are delivered:

### `comment` (Default — Recommended)
Posts a structured report as a PR comment. Updates the existing
comment on re-runs instead of creating duplicates. No files are
committed to the branch.

```yaml
output_mode: "comment"
```

### `commit`
Commits the generated test files directly to the PR branch.
Useful if you want to review and keep the generated tests.
No PR comment is posted.

```yaml
output_mode: "commit"
```

### `both`
Posts the PR comment AND commits the generated test files to the branch.

```yaml
output_mode: "both"
```

---

## Model Selection

| Model | Speed | Quality | Cost | Best For |
|---|---|---|---|---|
| `gpt-4.1` | Fast | High | Low | Default — best balance for CI/CD |
| `gpt-4.1-mini` | Fastest | Good | Lowest | High PR volume, cost-sensitive teams |
| `gpt-4o` | Medium | Highest | Higher | Complex files with many functions |
| `o3` | Slow | Highest | Highest | Security-critical code requiring deep analysis |

**Recommendation:** Start with `gpt-4.1` (default). Switch to
`gpt-4.1-mini` if costs exceed your budget. Use `gpt-4o` only for
particularly complex services.

---

## Coverage Threshold Guide

| Threshold | Strictness | Recommended For |
|---|---|---|
| `"60"` | Low | Legacy codebases with no existing tests |
| `"70"` | Moderate | Teams just starting to adopt testing |
| `"80"` | Standard | Default — recommended for most teams |
| `"90"` | High | Security-critical services (e.g. auth, payments) |
| `"95"` | Very High | Compliance-driven codebases (SOC2, HIPAA) |

---

## Environment Variables

These environment variables must be set in the workflow file
and passed to the composite action via the `env:` block.

### All Services

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key. Always load from `${{ secrets.OPENAI_API_KEY }}` |
| `GITHUB_TOKEN` | Yes | Auto-provided by GitHub Actions |

### FastAPI Service

| Variable | Required | Default | Description |
|---|---|---|---|
| `JWT_SECRET` | Yes | — | JWT signing secret used in tests to generate valid tokens |
| `JWT_ALGORITHM` | No | `HS256` | JWT algorithm |
| `JWT_AUDIENCE` | No | `zyloch-api` | Expected JWT audience claim |
| `MONGODB_URI` | Yes | — | MongoDB connection string for integration tests |
| `MONGODB_DB_NAME` | No | `zyloch_test` | Test database name |
| `ANTHROPIC_API_KEY` | No | placeholder | Anthropic API key — use a test placeholder for CI |
| `OPENAI_API_KEY` | No | placeholder | OpenAI key for app LLM calls — separate from the test generation key |
| `GOOGLE_GENAI_API_KEY` | No | placeholder | Google GenAI key |
| `GCP_DLP_PROJECT` | No | placeholder | GCP project ID for DLP |
| `GITHUB_APP_ID` | No | placeholder | GitHub App ID for integration tests |
| `GITHUB_WEBHOOK_SECRET` | No | placeholder | Webhook secret for signature verification tests |
| `FIELD_ENCRYPTION_KEY` | No | placeholder | Fernet encryption key for sensitive field tests |

### Node.js Service

| Variable | Required | Default | Description |
|---|---|---|---|
| `JWT_SECRET` | Yes | — | JWT signing secret used in tests |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis URL for BullMQ queue tests |
| `MONGODB_URI` | No | — | MongoDB URI for integration tests |
| `NODE_ENV` | No | `test` | Node environment — always set to `test` in CI |

### Next.js Service

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | No | `http://localhost:3000` | API base URL — mocked in most tests |

---

## GitHub Secrets Reference

| Secret Name | Scope | Description |
|---|---|---|
| `OPENAI_API_KEY` | Org or repo | OpenAI API key for test generation |
| `GITHUB_TOKEN` | Auto-provided | GitHub token — no setup needed |
| `JWT_SECRET` | Org or repo | Used only if you pass it as an env var |
| `GITHUB_WEBHOOK_SECRET` | Repo | Webhook secret for the GitHub App |
| `FIELD_ENCRYPTION_KEY` | Repo | Encryption key for sensitive fields |

**How to add a secret at organisation level:**
1. GitHub → Organisation Settings → Secrets and variables → Actions
2. New organisation secret → Enter name and value
3. Select which repos can access it (All repos or specific repos)

**How to add a secret at repo level:**
1. Repo → Settings → Secrets and variables → Actions
2. New repository secret → Enter name and value

---

## Service Detection Configuration

When `service_type` is set to `auto`, the system detects the service
type from file paths and code content using these rules:

### Next.js Detection
Files matching any of these patterns are classified as Next.js:
```
*.tsx, *.jsx
next.config.*
app/*page.*
components/
pages/
tailwind.config.*
```
Or files containing: `from 'react'`, `from 'next/`, `useState`, `useEffect`

### Node/Express Detection
Files matching:
```
*.js, *.ts (outside of Next.js context)
routes/
controllers/
middleware/
models/*.js, models/*.ts
package.json
```
Or files containing: `require('express')`, `router.get(`, `mongoose.model`

### FastAPI Detection
Files matching:
```
*.py
routers/
schemas/
models/*.py
dependencies/
tests/*.py
```
Or files containing: `from fastapi`, `@router.`, `BaseModel`, `Depends(`

### Files Always Skipped
Regardless of detection, these files are never processed:
```
*.lock files
*.min.js
node_modules/
.next/
dist/
build/
__pycache__/
*.pyc
coverage/
*.generated.*
migrations/
.env files
```

---

## Monorepo Configuration

For monorepos set `repo_type: "monorepo"` and list service directories:

```yaml
- name: Run Auto Test Generation
  uses: YOUR_ORG/utility-commons/.github/actions/auto-test-gen@main
  with:
    service_type:      "auto"
    repo_type:         "monorepo"
    monorepo_services: "frontend,backend,api"
```

The system will:
1. Detect which service directory each changed file belongs to
2. Apply the correct service type and prompt for that directory
3. Run the appropriate test framework per service
4. Combine all results into a single PR comment grouped by service

---

## Adjusting Per-Repo Settings

Each app repo can override the default settings independently.
There is no global config file — settings are per workflow file.

### Example — Stricter settings for a security-critical service
```yaml
with:
  coverage_threshold:   "90"    # stricter than default 80%
  fail_on_test_failure: "true"
  openai_model:         "gpt-4o" # higher quality for security code
  max_tokens:           "6000"   # more tokens for complex analysis
```

### Example — Lighter settings for a frontend repo
```yaml
with:
  coverage_threshold:   "70"        # more lenient for UI code
  fail_on_test_failure: "true"
  openai_model:         "gpt-4.1-mini" # faster and cheaper
  max_tokens:           "3000"
```

### Example — Commit generated tests to branch
```yaml
with:
  output_mode:     "both"
  test_output_dir: "tests/generated"  # custom output directory
```

---

## Updating the System

Since all logic lives in `utility-commons`, updates apply
across every repo automatically:

### To update test generation prompts
Edit any file in `utility-commons/prompts/` and push to `main`.
All repos will use the updated prompt on the next PR run.

### To update the composite action logic
Edit any Python file in `.github/actions/auto-test-gen/` and push.
All repos pick up the change immediately — no updates needed in
individual repos.

### To pin a specific version (recommended for production)
Instead of tracking `@main`, pin to a specific commit or tag:
```yaml
uses: YOUR_ORG/utility-commons/.github/actions/auto-test-gen@v1.0.0
```

Create a release tag in `utility-commons` when the system is stable.

---

## Quick Reference

```
KEY INPUTS
  openai_api_key        Required. From ${{ secrets.OPENAI_API_KEY }}
  github_token          Required. Use ${{ secrets.GITHUB_TOKEN }}
  service_type          auto | nextjs | node | fastapi
  repo_type             individual | monorepo
  coverage_threshold    Default: 80. Range: 0-100
  fail_on_test_failure  Default: true
  output_mode           comment | commit | both
  openai_model          Default: gpt-4.1
  max_tokens            Default: 4000

OUTPUT MODES
  comment   PR comment only — no files committed
  commit    Commit test files to branch — no comment
  both      PR comment + committed test files

MODEL GUIDE
  gpt-4.1        Default — best balance
  gpt-4.1-mini   Cheapest — high volume PRs
  gpt-4o         Highest quality — complex code

COVERAGE THRESHOLDS
  60   Legacy codebases
  70   Teams starting testing
  80   Standard (default)
  90   Security-critical services
  95   Compliance-driven (SOC2)

UPDATE UTILITY-COMMONS TO UPDATE ALL REPOS
  prompts/          → changes test generation behaviour
  action scripts    → changes core workflow logic
  No changes needed in individual app repos
```
