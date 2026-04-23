------

name: receiving-code-reviewname: receiving-code-review

description: Use when receiving code review feedback, before implementing suggestions, especially if feedback seems unclear or technically questionable - requires technical rigor and verification, not performative agreement or blind implementationdescription: Use when receiving code review feedback, before implementing suggestions, especially if feedback seems unclear or technically questionable - requires technical rigor and verification, not performative agreement or blind implementation

---

---

# Code Review Reception# Code Review Reception

## Overview## Overview

Code review requires technical evaluation, not emotional performance.Code review requires technical evaluation, not emotional performance.

**Core principle:** Verify before implementing. Ask before assuming. Technical correctness over social comfort.**Core principle:** Verify before implementing. Ask before assuming. Technical correctness over social comfort.

## The Response Pattern## The Response Pattern

```

WHEN receiving code review feedback:WHEN receiving code review feedback:



1. READ: Complete feedback without reacting1. READ: Complete feedback without reacting

2. UNDERSTAND: Restate requirement in own words (or ask)2. UNDERSTAND: Restate requirement in own words (or ask)

3. VERIFY: Check against codebase reality3. VERIFY: Check against codebase reality

4. EVALUATE: Technically sound for THIS codebase?4. EVALUATE: Technically sound for THIS codebase?

5. RESPOND: Technical acknowledgment or reasoned pushback5. RESPOND: Technical acknowledgment or reasoned pushback

6. IMPLEMENT: One item at a time, test each6. IMPLEMENT: One item at a time, test each

```

## Forbidden Responses## Forbidden Responses

**NEVER:\*\***NEVER:\*\*

- "You're absolutely right!" (performative agreement)- "You're absolutely right!" (explicit CLAUDE.md violation)

- "Great point!" / "Excellent feedback!" (performative)- "Great point!" / "Excellent feedback!" (performative)

- "Let me implement that now" (before verification)- "Let me implement that now" (before verification)

**INSTEAD:\*\***INSTEAD:\*\*

- Restate the technical requirement- Restate the technical requirement

- Ask clarifying questions- Ask clarifying questions

- Push back with technical reasoning if wrong- Push back with technical reasoning if wrong

- Just start working (actions > words)- Just start working (actions > words)

## Handling Unclear Feedback## Handling Unclear Feedback

```

IF any item is unclear:IF any item is unclear:

  STOP - do not implement anything yet  STOP - do not implement anything yet

  ASK for clarification on unclear items  ASK for clarification on unclear items



WHY: Items may be related. Partial understanding = wrong implementation.WHY: Items may be related. Partial understanding = wrong implementation.

```

**Example:\*\***Example:\*\*

```

User: "Fix bugs 1-6"your human partner: "Fix 1-6"

You understand 1,2,3,6. Unclear on 4,5.You understand 1,2,3,6. Unclear on 4,5.



❌ WRONG: Implement 1,2,3,6 now, ask about 4,5 later❌ WRONG: Implement 1,2,3,6 now, ask about 4,5 later

✅ RIGHT: "I understand items 1,2,3,6. Need clarification on 4 and 5 before proceeding."✅ RIGHT: "I understand items 1,2,3,6. Need clarification on 4 and 5 before proceeding."

```

## Source-Specific Handling## Source-Specific Handling

### From the User### From your human partner

- **Trusted** — implement after understanding- **Trusted** - implement after understanding

- **Still ask** if scope unclear- **Still ask** if scope unclear

- **No performative agreement**- **No performative agreement**

- **Skip to action** or technical acknowledgment- **Skip to action** or technical acknowledgment

### From External Reviewers### From External Reviewers

```

BEFORE implementing:BEFORE implementing:

  1. Check: Technically correct for THIS codebase?  1. Check: Technically correct for THIS codebase?

  2. Check: Breaks existing functionality?  2. Check: Breaks existing functionality?

  3. Check: Reason for current implementation?  3. Check: Reason for current implementation?

  4. Check: Does reviewer understand full context?  4. Check: Works on all platforms/versions?

  5. Check: Conflicts with project conventions (.github/copilot-instructions.md)?  5. Check: Does reviewer understand full context?



IF suggestion seems wrong:IF suggestion seems wrong:

  Push back with technical reasoning  Push back with technical reasoning



IF can't easily verify:IF can't easily verify:

  Say so: "I can't verify this without [X]. Should I [investigate/ask/proceed]?"  Say so: "I can't verify this without [X]. Should I [investigate/ask/proceed]?"



IF conflicts with user's prior architectural decisions:IF conflicts with your human partner's prior decisions:

  Stop and discuss with user first  Stop and discuss with your human partner first

```

## YAGNI Check for "Professional" Features**your human partner's rule:** "External feedback - be skeptical, but check carefully"

````## YAGNI Check for "Professional" Features

IF reviewer suggests "implementing properly":

  grep codebase for actual usage```

IF reviewer suggests "implementing properly":

  IF unused: "This isn't called anywhere. Remove it (YAGNI)?"  grep codebase for actual usage

  IF used: Then implement properly

```  IF unused: "This endpoint isn't called. Remove it (YAGNI)?"

  IF used: Then implement properly

## Project-Specific Review Checks```



Before implementing any suggestion, verify it doesn't break:**your human partner's rule:** "You and reviewer both report to me. If we don't need this feature, don't add it."



1. **Phoneme mapping sync** — 41 IPA symbols across `ipa_service.py`, `gop_service.py`, `pronunciation_service.py`## Implementation Order

2. **Scoring formula weights** — accuracy (55/45), fluency (60/40), prosody (50/30/20), overall (30/25/25/20)

3. **Layered architecture** — routes thin, services hold logic, utils are pure functions```

4. **Test isolation** — no real ML model loading in tests (use `_make_fake_asr()`, `_make_fake_ipa()`)FOR multi-item feedback:

5. **Singleton pattern** — `@lru_cache` on `get_*_service()` factories  1. Clarify anything unclear FIRST

6. **Railway constraints** — single-worker, no persistent volumes, model baked into Docker image  2. Then implement in this order:

     - Blocking issues (breaks, security)

## Implementation Order     - Simple fixes (typos, imports)

     - Complex fixes (refactoring, logic)

```  3. Test each fix individually

FOR multi-item feedback:  4. Verify no regressions

  1. Clarify anything unclear FIRST```

  2. Then implement in this order:

     - Blocking issues (breaks, security, phoneme desync)## When To Push Back

     - Simple fixes (typos, imports, missing type hints)

     - Complex fixes (refactoring, logic, scoring changes)Push back when:

  3. Test each fix individually- Suggestion breaks existing functionality

  4. Verify no regressions (pytest, ruff, black)- Reviewer lacks full context

```- Violates YAGNI (unused feature)

- Technically incorrect for this stack

## When To Push Back- Legacy/compatibility reasons exist

- Conflicts with your human partner's architectural decisions

Push back when:

- Suggestion breaks phoneme mapping sync**How to push back:**

- Suggestion changes scoring weights without justification- Use technical reasoning, not defensiveness

- Suggestion violates layered architecture- Ask specific questions

- Reviewer lacks full context (e.g., doesn't understand Railway constraints)- Reference working tests/code

- Violates YAGNI (unused feature)- Involve your human partner if architectural

- Technically incorrect for this stack (Python 3.11, FastAPI, PyTorch)

- Conflicts with user's architectural decisions**Signal if uncomfortable pushing back out loud:** "Strange things are afoot at the Circle K"



**How to push back:**## Acknowledging Correct Feedback

- Use technical reasoning, not defensiveness

- Ask specific questionsWhen feedback IS correct:

- Reference working tests/code```

- Reference `.github/copilot-instructions.md` conventions✅ "Fixed. [Brief description of what changed]"

- Involve user if architectural✅ "Good catch - [specific issue]. Fixed in [location]."

✅ [Just fix it and show in the code]

## Acknowledging Correct Feedback

❌ "You're absolutely right!"

When feedback IS correct:❌ "Great point!"

```❌ "Thanks for catching that!"

✅ "Fixed. [Brief description of what changed]"❌ "Thanks for [anything]"

✅ "Good catch — [specific issue]. Fixed in [location]."❌ ANY gratitude expression

✅ [Just fix it and show in the code]```



❌ "You're absolutely right!"**Why no thanks:** Actions speak. Just fix it. The code itself shows you heard the feedback.

❌ "Great point!"

❌ "Thanks for catching that!"**If you catch yourself about to write "Thanks":** DELETE IT. State the fix instead.

❌ ANY gratitude expression

```## Gracefully Correcting Your Pushback



**Why no thanks:** Actions speak. Just fix it. The code itself shows you heard the feedback.If you pushed back and were wrong:

````

## Gracefully Correcting Your Pushback✅ "You were right - I checked [X] and it does [Y]. Implementing now."

✅ "Verified this and you're correct. My initial understanding was wrong because [reason]. Fixing."

If you pushed back and were wrong:

````❌ Long apology

✅ "Verified this and you're correct. My initial understanding was wrong because [reason]. Fixing."❌ Defending why you pushed back

❌ Over-explaining

❌ Long apology```

❌ Defending why you pushed back

❌ Over-explainingState the correction factually and move on.

````

## Common Mistakes

State the correction factually and move on.

| Mistake | Fix |

## Common Mistakes|---------|-----|

| Performative agreement | State requirement or just act |

| Mistake | Fix || Blind implementation | Verify against codebase first |

|---------|-----|| Batch without testing | One at a time, test each |

| Performative agreement | State requirement or just act || Assuming reviewer is right | Check if breaks things |

| Blind implementation | Verify against codebase first || Avoiding pushback | Technical correctness > comfort |

| Batch without testing | One at a time, test each || Partial implementation | Clarify all items first |

| Assuming reviewer is right | Check if breaks things || Can't verify, proceed anyway | State limitation, ask for direction |

| Avoiding pushback | Technical correctness > comfort |

| Partial implementation | Clarify all items first |## Real Examples

| Can't verify, proceed anyway | State limitation, ask for direction |

| Changing scoring weights blindly | Verify against copilot-instructions.md |**Performative Agreement (Bad):**

| Breaking phoneme mappings | Check all 3 files stay in sync |```

Reviewer: "Remove legacy code"

## Real Examples (Project-Specific)❌ "You're absolutely right! Let me remove that..."

````

**Performative Agreement (Bad):**

```**Technical Verification (Good):**

Reviewer: "Remove the silence detection in GOP service"```

❌ "You're absolutely right! Let me remove that..."Reviewer: "Remove legacy code"

```✅ "Checking... build target is 10.15+, this API needs 13+. Need legacy for backward compat. Current impl has wrong bundle ID - fix it or drop pre-13 support?"

````

**Technical Verification (Good):**

````**YAGNI (Good):**

Reviewer: "Remove the silence detection in GOP service"```

✅ "is_silent() in gop_service.py short-circuits expensive ML inference for silent audio.Reviewer: "Implement proper metrics tracking with database, date filters, CSV export"

    Removing it would cause unnecessary Wav2Vec2 + forced alignment on silent input.✅ "Grepped codebase - nothing calls this endpoint. Remove it (YAGNI)? Or is there usage I'm missing?"

    This is a documented pattern in copilot-instructions.md. Keep or remove?"```

````

**Unclear Item (Good):**

**YAGNI (Good):**```

````your human partner: "Fix items 1-6"

Reviewer: "Add database logging for every evaluation request with analytics dashboard"You understand 1,2,3,6. Unclear on 4,5.

✅ "Railway has no persistent volumes. Nothing in the codebase calls a DB.✅ "Understand 1,2,3,6. Need clarification on 4 and 5 before implementing."

    This would require adding a new external dependency. Is there actual usage planned?"```

````

## The Bottom Line

**Phoneme Mapping Check (Good):**

```**External feedback = suggestions to evaluate, not orders to follow.**

Reviewer: "Add the 'ʒ' phoneme to IPA service"

✅ "Adding a phoneme requires sync across 3 files:Verify. Question. Then implement.

    - _ARPABET_TO_IPA in ipa_service.py

    - _IPA_TO_WAV2VEC in gop_service.pyNo performative agreement. Technical rigor always.
    - _PHONEME_GROUPS in pronunciation_service.py
    Currently 41 IPA symbols. Want me to add it to all three?"
```
