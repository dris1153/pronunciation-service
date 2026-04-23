------

name: code-reviewname: code-review

description: Use when receiving code review feedback (especially if unclear or technically questionable), when completing tasks or major features requiring review before proceeding, or before making any completion/success claims. Covers three practices - receiving feedback with technical rigor over performative agreement, requesting reviews via code-reviewer agent, and verification gates requiring evidence before any status claims. Essential for pull requests, feature phases, and preventing false completion claims.description: Use when receiving code review feedback (especially if unclear or technically questionable), when completing tasks or major features requiring review before proceeding, or before making any completion/success claims. Covers three practices - receiving feedback with technical rigor over performative agreement, requesting reviews via code-reviewer subagent, and verification gates requiring evidence before any status claims. Essential for subagent-driven development, pull requests, and preventing false completion claims.

---

---

# Code Review# Code Review

Guide proper code review practices emphasizing technical rigor, evidence-based claims, and verification over performative responses.Guide proper code review practices emphasizing technical rigor, evidence-based claims, and verification over performative responses.

## Overview## Overview

Code review requires three distinct practices:Code review requires three distinct practices:

1. **Receiving feedback** - Technical evaluation over performative agreement1. **Receiving feedback** - Technical evaluation over performative agreement

2. **Requesting reviews** - Systematic review via code-reviewer agent2. **Requesting reviews** - Systematic review via code-reviewer subagent

3. **Verification gates** - Evidence before any completion claims3. **Verification gates** - Evidence before any completion claims

Each practice has specific triggers and protocols detailed in reference files.Each practice has specific triggers and protocols detailed in reference files.

## Core Principle## Core Principle

Always honouring **YAGNI**, **KISS**, and **DRY** principles.Always honoring **YAGNI**, **KISS**, and **DRY** principles.

**Be honest, be brutal, straight to the point, and be concise.\*\***Be honest, be brutal, straight to the point, and be concise.\*\*

**Technical correctness over social comfort.** Verify before implementing. Ask before assuming. Evidence before claims.**Technical correctness over social comfort.** Verify before implementing. Ask before assuming. Evidence before claims.

## Project-Specific Context## When to Use This Skill

This skill applies to the **Pronunciation Validation Service** — a FastAPI + Wav2Vec2 pronunciation evaluation API.### Receiving Feedback

Trigger when:

| What to verify | How |- Receiving code review comments from any source

| ----------------------- | -------------------------------------------------------------------------- |- Feedback seems unclear or technically questionable

| **Tests pass** | `python -m pytest tests/ --tb=short -q` (expect ~267 tests) |- Multiple review items need prioritization

| **Linting clean** | `ruff check app/ tests/ --output-format=concise` |- External reviewer lacks full context

| **Formatting clean** | `black --check app/ tests/` |- Suggestion conflicts with existing decisions

| **Phoneme mappings** | 41 IPA symbols in sync across 3 files |

| **Scoring formulas** | accuracy/completeness/fluency/prosody/overall weights unchanged |**Reference:** `references/code-review-reception.md`

| **Code-reviewer agent** | `.github/instructions/agents/code-reviewer.instructions.md` |

### Requesting Review

**Environment:** All commands run via conda env `pronun`:Trigger when:

````- Completing tasks in subagent-driven development (after EACH task)

conda run -n pronun --no-capture-output <command>- Finishing major features or refactors

```- Before merging to main branch

- Stuck and need fresh perspective

## When to Use This Skill- After fixing complex bugs



### Receiving Feedback**Reference:** `references/requesting-code-review.md`

Trigger when:

- Receiving code review comments from any source### Verification Gates

- Feedback seems unclear or technically questionableTrigger when:

- Multiple review items need prioritization- About to claim tests pass, build succeeds, or work is complete

- Suggestion conflicts with existing architectural decisions (layered architecture, singleton services, phoneme mappings)- Before committing, pushing, or creating PRs

- Moving to next task

**Reference:** `references/code-review-reception.md`- Any statement suggesting success/completion

- Expressing satisfaction with work

### Requesting Review

Trigger when:**Reference:** `references/verification-before-completion.md`

- Completing a scoring phase (accuracy, completeness, fluency, prosody)

- Finishing major features or refactors## Quick Decision Tree

- Before merging to main branch

- Before deploying to Railway```

- After fixing complex bugs (especially in ML pipeline)SITUATION?

│

**Reference:** `references/requesting-code-review.md`├─ Received feedback

│  ├─ Unclear items? → STOP, ask for clarification first

### Verification Gates│  ├─ From human partner? → Understand, then implement

Trigger when:│  └─ From external reviewer? → Verify technically before implementing

- About to claim tests pass, build succeeds, or work is complete│

- Before committing, pushing, or creating PRs├─ Completed work

- Moving to next phase/task│  ├─ Major feature/task? → Request code-reviewer subagent review

- Any statement suggesting success/completion│  └─ Before merge? → Request code-reviewer subagent review

- Expressing satisfaction with work│

└─ About to claim status

**Reference:** `references/verification-before-completion.md`   ├─ Have fresh verification? → State claim WITH evidence

   └─ No fresh verification? → RUN verification command first

## Quick Decision Tree```



```## Receiving Feedback Protocol

SITUATION?

│### Response Pattern

├─ Received feedbackREAD → UNDERSTAND → VERIFY → EVALUATE → RESPOND → IMPLEMENT

│  ├─ Unclear items? → STOP, ask for clarification first

│  ├─ From user? → Understand, then implement### Key Rules

│  └─ From external reviewer? → Verify technically before implementing- ❌ No performative agreement: "You're absolutely right!", "Great point!", "Thanks for [anything]"

│- ❌ No implementation before verification

├─ Completed work- ✅ Restate requirement, ask questions, push back with technical reasoning, or just start working

│  ├─ Scoring phase complete? → Run full verification suite, then request code-reviewer- ✅ If unclear: STOP and ask for clarification on ALL unclear items first

│  ├─ Major feature/refactor? → Request code-reviewer agent review- ✅ YAGNI check: grep for usage before implementing suggested "proper" features

│  └─ Before merge/deploy? → Request code-reviewer agent review

│### Source Handling

└─ About to claim status- **Human partner:** Trusted - implement after understanding, no performative agreement

   ├─ Have fresh verification output? → State claim WITH evidence- **External reviewers:** Verify technically correct, check for breakage, push back if wrong

   └─ No fresh verification? → RUN verification commands first

```**Full protocol:** `references/code-review-reception.md`



## Receiving Feedback Protocol## Requesting Review Protocol



### Response Pattern### When to Request

READ → UNDERSTAND → VERIFY → EVALUATE → RESPOND → IMPLEMENT- After each task in subagent-driven development

- After major feature completion

### Key Rules- Before merge to main

- ❌ No performative agreement: "You're absolutely right!", "Great point!", "Thanks for [anything]"

- ❌ No implementation before verification### Process

- ✅ Restate requirement, ask questions, push back with technical reasoning, or just start working1. Get git SHAs: `BASE_SHA=$(git rev-parse HEAD~1)` and `HEAD_SHA=$(git rev-parse HEAD)`

- ✅ If unclear: STOP and ask for clarification on ALL unclear items first2. Dispatch code-reviewer subagent via Task tool with: WHAT_WAS_IMPLEMENTED, PLAN_OR_REQUIREMENTS, BASE_SHA, HEAD_SHA, DESCRIPTION

- ✅ YAGNI check: grep for usage before implementing suggested "proper" features3. Act on feedback: Fix Critical immediately, Important before proceeding, note Minor for later

- ✅ Check if suggestion breaks phoneme mapping sync (41 IPA symbols across 3 files)

- ✅ Check if suggestion changes scoring formula weights without justification**Full protocol:** `references/requesting-code-review.md`



### Source Handling## Verification Gates Protocol

- **User:** Trusted — implement after understanding, no performative agreement

- **External reviewers:** Verify technically correct, check for breakage, push back if wrong### The Iron Law

**NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE**

**Full protocol:** `references/code-review-reception.md`

### Gate Function

## Requesting Review ProtocolIDENTIFY command → RUN full command → READ output → VERIFY confirms claim → THEN claim



### When to RequestSkip any step = lying, not verifying

- After completing a scoring phase or major feature

- Before merge to main### Requirements

- Before Railway deployment- Tests pass: Test output shows 0 failures

- Build succeeds: Build command exit 0

### Process- Bug fixed: Test original symptom passes

1. Get git diff: `git --no-pager diff HEAD~N --name-only` (identify changed files)- Requirements met: Line-by-line checklist verified

2. Reference the code-reviewer agent at `.github/instructions/agents/code-reviewer.instructions.md`

3. Provide context: what was implemented, which phase/feature, what files changed### Red Flags - STOP

4. Act on feedback: Fix Critical immediately, High before proceeding, note Medium/Low for laterUsing "should"/"probably"/"seems to", expressing satisfaction before verification, committing without verification, trusting agent reports, ANY wording implying success without running verification



**Full protocol:** `references/requesting-code-review.md`**Full protocol:** `references/verification-before-completion.md`



## Verification Gates Protocol## Integration with Workflows



### The Iron Law- **Subagent-Driven:** Review after EACH task, verify before moving to next

**NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE**- **Pull Requests:** Verify tests pass, request code-reviewer review before merge

- **General:** Apply verification gates before any status claims, push back on invalid feedback

### Gate Function

IDENTIFY command → RUN full command → READ output → VERIFY confirms claim → THEN claim## Bottom Line



Skip any step = lying, not verifying1. Technical rigor over social performance - No performative agreement

2. Systematic review processes - Use code-reviewer subagent

### Project-Specific Verification Suite3. Evidence before claims - Verification gates always

````

# 1. Tests (must show ~267 passed, 0 failed)Verify. Question. Then implement. Evidence. Then claim.

python -m pytest tests/ --tb=short -q

# 2. Linting (must show 0 errors)

ruff check app/ tests/ --output-format=concise

# 3. Formatting (must show "All done!")

black --check app/ tests/

```

### Requirements
- Tests pass: pytest output shows 0 failures, ~267 passed
- Linting clean: ruff shows 0 errors
- Formatting clean: black --check passes
- Bug fixed: test original symptom passes
- Scoring formula correct: weights match copilot-instructions.md
- Phoneme mappings synced: 41 IPA symbols across 3 files

### Red Flags — STOP
Using "should"/"probably"/"seems to", expressing satisfaction before verification, committing without verification, ANY wording implying success without running verification

**Full protocol:** `references/verification-before-completion.md`

## Integration with Workflows

- **Scoring Phases:** Review after EACH phase (accuracy, completeness, fluency, prosody), verify before moving to next
- **Pull Requests:** Verify full suite passes, request code-reviewer review before merge
- **Railway Deployment:** Run full verification suite, ensure Docker build succeeds
- **Bug Fixes:** Verify the fix, run full test suite, check for regressions
- **General:** Apply verification gates before any status claims, push back on invalid feedback

## Bottom Line

1. Technical rigor over social performance — No performative agreement
2. Systematic review processes — Use code-reviewer agent
3. Evidence before claims — Verification gates always

Verify. Question. Then implement. Evidence. Then claim.
```
