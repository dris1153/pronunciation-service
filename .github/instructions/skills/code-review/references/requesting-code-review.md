---
name: requesting-code-review
description: Use when completing tasks, implementing major features or scoring phases, or before merging — dispatches code-reviewer agent to review implementation against requirements before proceeding
---

# Requesting Code Review

Dispatch code-reviewer agent to catch issues before they cascade.

**Core principle:** Review early, review often.

## When to Request Review

**Mandatory:**

- After completing a scoring phase (accuracy, completeness, fluency, prosody)
- After completing a major feature or refactor
- Before merge to main branch
- Before deploying to Railway

**Optional but valuable:**

- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bugs (especially ML pipeline)

## How to Request

**1. Identify what changed:**

```
git --no-pager diff HEAD~N --name-only
git --no-pager log --oneline -5
```

**2. Reference the code-reviewer agent:**

The code-reviewer agent is defined at `.github/instructions/agents/code-reviewer.instructions.md`. It knows the full project context — layered architecture, scoring formulas, phoneme mappings, Railway constraints.

Provide the code-reviewer with:

- **WHAT_WAS_IMPLEMENTED** — what you just built (e.g., "Phase 3: Prosody scoring + monotone detection")
- **FILES_CHANGED** — list of modified/added files
- **REQUIREMENTS** — what it should do (reference the phase plan or user requirements)
- **GIT_RANGE** — commit range to review (e.g., `HEAD~5..HEAD`)

**3. Act on feedback:**

- Fix 🔴 Critical issues immediately
- Fix 🟠 High issues before proceeding
- Note 🟡 Medium issues for later
- 🟢 Low issues are optional
- Push back if reviewer is wrong (with reasoning)

## Example (Project-Specific)

```
[Just completed Phase 3: Prosody scoring]

You: Let me request code review before proceeding.

Changed files:
  - app/services/prosody_service.py (NEW)
  - app/services/pronunciation_service.py (modified — 4-score overall)
  - app/models/schemas.py (modified — ProsodyResult, prosody_score)
  - app/core/config.py (modified — prosody settings)
  - app/application.py (modified — prosody preload)
  - tests/test_prosody.py (NEW — 25 tests)
  - tests/conftest.py (modified — prosody fixtures)

[Reference code-reviewer agent]
  WHAT_WAS_IMPLEMENTED: Phase 3 — Prosody scoring via librosa.pyin, monotone detection,
                        4-score overall formula
  FILES_CHANGED: [list above]
  REQUIREMENTS: F0 extraction, variance/range/contour scoring, monotone cap at 40,
                voiced ratio guard, 4-tier overall formula
  GIT_RANGE: HEAD~8..HEAD

[Code-reviewer returns]:
  Overall: Good architecture, clean service isolation
  🟠 High: Documentation drift — README still shows 3-score formula
  🟡 Medium: Missing edge case test for all-silent prosody input
  🟢 Low: Config variable naming could be more descriptive
  ✅ Positive: Clean singleton pattern, good mock isolation

You: [Fix documentation, add edge case test]
[Continue to next phase]
```

## Integration with Workflows

**Scoring Phases:**

- Review after EACH phase
- Catch issues before they compound across phases
- Fix before moving to next phase

**Pull Requests:**

- Review before merge
- Ensure full verification suite passes first

**Railway Deployment:**

- Review before deploy
- Check Docker build, health check, env vars

**Bug Fixes:**

- Review after complex bug fixes
- Ensure fix doesn't introduce regressions

## Red Flags

**Never:**

- Skip review because "it's simple"
- Ignore 🔴 Critical issues
- Proceed with unfixed 🟠 High issues
- Argue with valid technical feedback about phoneme mappings or scoring formulas

**If reviewer wrong:**

- Push back with technical reasoning
- Show code/tests that prove it works
- Reference `.github/copilot-instructions.md` conventions
- Request clarification
