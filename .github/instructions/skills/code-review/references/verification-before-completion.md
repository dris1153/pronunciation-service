---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Project-Specific Verification Suite

All commands must run in the conda `pronun` environment:

### Tests

```
python -m pytest tests/ --tb=short -q
```

**Expected:** ~267 passed, 0 failed, 0 errors

### Linting

```
ruff check app/ tests/ --output-format=concise
```

**Expected:** 0 errors

### Formatting

```
black --check app/ tests/
```

**Expected:** "All done!" or "X files would be left unchanged"

### Full Verification (run all three)

```
python -m pytest tests/ --tb=short -q
ruff check app/ tests/ --output-format=concise
black --check app/ tests/
```

## Common Failures

| Claim                   | Requires                               | Not Sufficient               |
| ----------------------- | -------------------------------------- | ---------------------------- |
| Tests pass              | pytest output: 0 failures, ~267 passed | Previous run, "should pass"  |
| Linter clean            | ruff output: 0 errors                  | Partial check, extrapolation |
| Formatting clean        | black --check: exit 0                  | Linter passing               |
| Bug fixed               | Test original symptom: passes          | Code changed, assumed fixed  |
| Scoring formula correct | Weights match copilot-instructions.md  | "I used the right values"    |
| Phoneme mappings synced | All 3 files have 41 symbols            | Updated one file only        |
| Phase complete          | All tests + lint + format pass         | Tests pass alone             |
| Deploy ready            | Full suite + Docker build              | Tests pass locally           |

## Red Flags — STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Relying on partial verification
- Thinking "just this once"
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse                                  | Reality                       |
| --------------------------------------- | ----------------------------- |
| "Should work now"                       | RUN the verification          |
| "I'm confident"                         | Confidence ≠ evidence         |
| "Just this once"                        | No exceptions                 |
| "Linter passed"                         | Linter ≠ tests                |
| "Tests passed earlier"                  | Re-run fresh                  |
| "I only changed one line"               | One line can break everything |
| "Partial check is enough"               | Partial proves nothing        |
| "Different words so rule doesn't apply" | Spirit over letter            |

## Key Patterns

**Tests:**

```
✅ [Run pytest] [See: 267 passed, 0 failed] "All 267 tests pass"
❌ "Should pass now" / "Looks correct"
```

**Linting:**

```
✅ [Run ruff check] [See: 0 errors] "Linting clean"
❌ "I followed the conventions" (without running ruff)
```

**Scoring Formula:**

```
✅ [Read copilot-instructions.md] [Compare weights] "Weights match: accuracy 55/45, overall 30/25/25/20"
❌ "I used the documented weights"
```

**Phoneme Mappings:**

```
✅ [Count symbols in all 3 files] "All three files have 41 IPA symbols"
❌ "I updated all the mappings"
```

**Phase Completion:**

```
✅ [pytest: 267 passed] [ruff: 0 errors] [black: clean] "Phase 3 complete — all checks pass"
❌ "Tests pass, phase complete" (without linting/formatting)
```

**Requirements:**

```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, requirements met"
```

## When To Apply

**ALWAYS before:**

- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next phase/task
- Deploying to Railway

**Rule applies to:**

- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.
