# Auto Test Generation — Setup Guide

## What This System Does

This system automatically generates, runs, and reports test cases
on every pull request across your GitHub repositories — with zero
manual test writing required.

When a developer opens a PR:
1. The workflow detects exactly which files and functions changed
2. OpenAI generates comprehensive test cases for those changes
3. The tests are executed automatically
4. A structured report is posted as a PR comment showing pass/fail
   per test case, coverage percentage, and any failures
5. The PR is blocked from merging if tests fail or coverage drops
   below the configured threshold

Supports: **Next.js frontend**, **Node/Express backend**,
**FastAPI backend** — monorepo and individual repo setups.

---

## Architecture Overview

```
utility-commons/                         ← Central composite action repo
└── .github/
│   └── actions/
│       └── auto-test-gen/
│           ├── action.yml               ← Composite action definition
│           ├── parse_diff.py            ← PR diff parser + service detector
│           ├── generate_tests.py        ← OpenAI test generation engine
│           ├── run_tests.py             ← Test runner + coverage collector
│           └── post_comment.py          ← PR comment formatter and poster
└── prompts/
│   ├── nextjs_test_prompt.md            ← Next.js test generation prompt
│   ├── node_test_prompt.md              ← Node/Express test generation prompt
│   └── fastapi_test_prompt.md           ← FastAPI test generation prompt
└── workflow-templates/
    ├── nextjs-auto-test.yml             ← Copy to Next.js repos
    ├── node-auto-test.yml               ← Copy to Node/Express repos
    └── fastapi-auto-test.yml            ← Copy to FastAPI repos

Each app repo/                           ← Your frontend/backend repos
└── .github/
    └── workflows/
        └── auto-test-gen.yml            ← Lightweight caller workflow
```

---

## Prerequisites

Before deploying ensure the following are in place:

- [ ] GitHub organisation account with `utility-commons` repo created
- [ ] OpenAI account with an API key — set a billing limit of $20/month
- [ ] Admin access to all repos where the workflow will be deployed
- [ ] GitHub Actions enabled on all target repos
- [ ] Python 3.11+ available on GitHub-hosted runners (included by default)
- [ ] Node.js 20+ available on GitHub-hosted runners (included by default)

---

## Step 1 — Set Up the `utility-commons` Repo

### 1a — Create the folder structure

In your `utility-commons` repository create the following structure:

```bash
mkdir -p .github/actions/auto-test-gen
mkdir -p prompts
mkdir -p workflow-templates
```

### 1b — Copy the composite action files

Copy these files from this delivery into `utility-commons`:

```
.github/actions/auto-test-gen/action.yml
.github/actions/auto-test-gen/parse_diff.py
.github/actions/auto-test-gen/generate_tests.py
.github/actions/auto-test-gen/run_tests.py
.github/actions/auto-test-gen/post_comment.py
prompts/nextjs_test_prompt.md
prompts/node_test_prompt.md
prompts/fastapi_test_prompt.md
```

### 1c — Commit and push

```bash
git add .
git commit -m "feat: add auto-test-gen composite action"
git push origin main
```

---

## Step 2 — Add GitHub Secrets

The workflow requires two secrets. Add them at the **organisation
level** so all repos inherit them automatically, or at the
individual repo level if you prefer.

### Adding Secrets at Organisation Level (Recommended)

1. Go to your GitHub organisation settings
2. Click **Secrets and variables → Actions**
3. Click **New organisation secret**
4. Add each secret below

### Required Secrets

| Secret Name | Value | Where to Get It |
|---|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key | platform.openai.com → API keys |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | No action needed — already available |

**Note:** `GITHUB_TOKEN` is automatically provided by GitHub Actions
in every workflow run. You do not need to create it manually.

### Setting a Billing Limit on OpenAI (Important)

To prevent unexpected costs:
1. Go to platform.openai.com → Settings → Billing
2. Click **Set a monthly budget**
3. Set a limit of **$20/month** to start
4. Increase as needed once you know your actual PR volume costs

---

## Step 3 — Update the Composite Action Reference

In every workflow template file, replace `YOUR_ORG` with your
actual GitHub organisation name.

**Find this line in each workflow template:**
```yaml
uses: YOUR_ORG/utility-commons/.github/actions/auto-test-gen@main
```

**Replace with your org name. Example:**
```yaml
uses: zyloch/utility-commons/.github/actions/auto-test-gen@main
```

Do this in all three workflow templates:
- `workflow-templates/nextjs-auto-test.yml`
- `workflow-templates/node-auto-test.yml`
- `workflow-templates/fastapi-auto-test.yml`

---

## Step 4 — Deploy to Each App Repo

For each repository, copy the correct workflow template into the
repo's `.github/workflows/` folder.

### Next.js Frontend Repo
```bash
# In your Next.js repo
mkdir -p .github/workflows
cp /path/to/workflow-templates/nextjs-auto-test.yml \
   .github/workflows/auto-test-gen.yml

git add .github/workflows/auto-test-gen.yml
git commit -m "feat: add auto test generation workflow"
git push
```

### Node/Express Backend Repo
```bash
# In your Node.js repo
mkdir -p .github/workflows
cp /path/to/workflow-templates/node-auto-test.yml \
   .github/workflows/auto-test-gen.yml

git add .github/workflows/auto-test-gen.yml
git commit -m "feat: add auto test generation workflow"
git push
```

### FastAPI Backend Repo
```bash
# In your FastAPI repo
mkdir -p .github/workflows
cp /path/to/workflow-templates/fastapi-auto-test.yml \
   .github/workflows/auto-test-gen.yml

git add .github/workflows/auto-test-gen.yml
git commit -m "feat: add auto test generation workflow"
git push
```

---

## Step 5 — Monorepo Setup (If Applicable)

If you have a monorepo containing multiple services, use a single
workflow file with the `monorepo` repo type and list your service
directories.

Create `.github/workflows/auto-test-gen.yml` in your monorepo:

```yaml
name: Auto Test Generation — Monorepo

on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [main, develop]

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number }}
  cancel-in-progress: true

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  auto-test-gen:
    runs-on: ubuntu-latest
    timeout-minutes: 45

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          ref: ${{ github.head_ref }}
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          npm ci || true
          pip install -r requirements.txt || true

      - name: Run Auto Test Generation
        uses: YOUR_ORG/utility-commons/.github/actions/auto-test-gen@main
        with:
          openai_api_key:       ${{ secrets.OPENAI_API_KEY }}
          github_token:         ${{ secrets.GITHUB_TOKEN }}
          service_type:         "auto"
          repo_type:            "monorepo"
          monorepo_services:    "frontend,backend,api"
          coverage_threshold:   "80"
          fail_on_test_failure: "true"
          output_mode:          "comment"
          openai_model:         "gpt-4.1"
          max_tokens:           "4000"
```

Replace `"frontend,backend,api"` with your actual service directory
names separated by commas.

---

## Step 6 — Verify the Setup

### Trigger a Test Run

Open a pull request against any branch. Add or modify a function
in any `.py`, `.ts`, `.tsx`, or `.js` file.

### What to Expect

Within 2-5 minutes you should see:

1. **GitHub Actions running** — visible in the PR's Checks tab
2. **PR comment posted** — a structured report appears on the PR
3. **Test results shown** — pass/fail per test case, coverage %
4. **PR blocked or approved** — based on test and coverage results

### Verification Checklist

- [ ] Workflow appears in the PR Checks tab
- [ ] PR comment is posted by `github-actions[bot]`
- [ ] Comment shows correct number of tests generated
- [ ] Comment shows pass/fail per test case
- [ ] Comment shows coverage percentage
- [ ] PR is blocked if tests fail
- [ ] PR is blocked if coverage is below threshold
- [ ] Workflow updates the existing comment on re-runs (not a new comment)

---

## Step 7 — Branch Protection Rules (Recommended)

To enforce that the auto-test workflow must pass before merging:

1. Go to repo **Settings → Branches**
2. Click **Add branch protection rule**
3. Set **Branch name pattern** to `main`
4. Enable **Require status checks to pass before merging**
5. Search for and add: `Generate and Run Tests`
6. Enable **Require branches to be up to date before merging**
7. Click **Save changes**

Repeat for `develop` if applicable.

---

## How the PR Comment Looks

Every PR will receive a comment like this:

```
✅ Auto Test Generation Report
Generated by auto-test-gen · 2026-05-20 10:30 UTC

Summary
| Metric           | Value | Status |
|-----------------|-------|--------|
| Tests Generated  | 12    | ℹ️     |
| Tests Passed     | 12    | ✅     |
| Tests Failed     | 0     | ✅     |
| Coverage         | 87%   | ✅ 87% |
| Overall Status   | —     | ✅ PASS|

Service Breakdown
▶ ✅ FastAPI Backend — 8/8 passed · Coverage: 87%
▶ ✅ Node / Express Backend — 4/4 passed · Coverage: 91%

Coverage
| Required | Actual | Status |
|----------|--------|--------|
| 80%      | 87%    | ✅ 87% |

✅ All checks passed
All 12 generated test cases passed and coverage meets the 80% threshold.
```

---

## Troubleshooting

| Issue | Likely Cause | Fix |
|---|---|---|
| Workflow not triggering | Branch not in trigger list | Add branch to `branches:` in workflow file |
| No PR comment posted | GITHUB_TOKEN permissions | Ensure `pull-requests: write` in workflow permissions |
| Tests not found | Wrong test output directory | Check `test_output_dir` matches the directory being scanned |
| OpenAI rate limit errors | Too many files changed in one PR | Increase `max_tokens` or reduce PR size |
| Coverage always 0% | pytest-cov not installed | Run `pip install pytest-cov` in setup step |
| Wrong service detected | Ambiguous file paths | Set `service_type` explicitly instead of `auto` |
| Composite action not found | Wrong org name in uses | Replace `YOUR_ORG` with actual org name |
| Tests fail to import | Missing project dependencies | Ensure `npm ci` or `pip install` runs before composite action |
| Redis connection error | Redis service not started | Add Redis service block to Node.js workflow |

---

## Cost Estimation

Approximate OpenAI API costs based on PR volume:

| PRs per Month | Avg Files Changed | Est. Monthly Cost |
|---|---|---|
| 20 PRs | 3 files each | ~$3-5/month |
| 50 PRs | 3 files each | ~$8-12/month |
| 100 PRs | 5 files each | ~$20-30/month |

Costs vary based on file size and function complexity.
Set a $20/month billing limit to start and adjust as needed.

---

## Extending the System

### Adjusting Coverage Threshold
In each workflow file change the `coverage_threshold` input:
```yaml
coverage_threshold: "90"   # increase for stricter requirement
coverage_threshold: "70"   # decrease for more lenient requirement
```

### Changing Output Mode
```yaml
output_mode: "comment"   # PR comment only (default)
output_mode: "commit"    # commit test files to branch
output_mode: "both"      # comment + commit
```

### Adding a New Repo
1. Copy the correct workflow template into `.github/workflows/auto-test-gen.yml`
2. Replace `YOUR_ORG` with your org name
3. Commit and push — the system is active immediately

### Updating the Test Generation Prompts
Edit any file in `utility-commons/prompts/` to change how tests
are generated across all repos — no changes needed in individual repos.
All repos pull from `utility-commons` at runtime.
