---
name: investigate-reviews
description: "Analyze PR review threads to detect endless fix-review loops. Identifies patterns like recurring root causes, incomplete parity fixes, and grep-based validation fragility. Run early to avoid multi-day whack-a-mole cycles."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:a666b1025b51864bfbb10195ad1940ed387886d33e6c15ede78985ee8a2519bd
Source-Hash: blake3:b825b61f03f5b719da37acd4e0747c0e0c353861081dbd95ec02cefe9320ddf5
Schema-Version: v1
-->

# investigate-reviews

Detect the "endless review loop" anti-pattern before it consumes days of effort.

## When to use

Run this skill when:
- A PR has received multiple rounds of bot reviews (coderabbitai, chatgpt-codex-connector, etc.)
- You've fixed several issues but new ones keep appearing
- You suspect fixes are creating new related issues rather than converging

## The loop pattern

```
1. Bot finds issue A in area X
2. You fix issue A
3. Bot finds issue B in area X (related to A, or caused by fix for A)
4. You fix issue B
5. Bot finds issue C...
6. Repeat until context exhaustion
```

## Analysis procedure

### Step 1: Fetch thread timeline

```bash
PR_NUMBER=<number>
REPO=<owner/repo>

gh api graphql -f query='
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100) {
        totalCount
        nodes {
          id
          isResolved
          comments(first: 1) {
            nodes {
              createdAt
              author { login }
              body
              path
            }
          }
        }
      }
    }
  }
}' -f owner="${REPO%%/*}" -f repo="${REPO##*/}" -F pr="$PR_NUMBER"
```

### Step 2: Group by date and author

Look for:
- **Multiple batches from same bot** on different days = loop indicator
- **Same file appearing across batches** = recurring root cause
- **Phrases like "Fresh evidence after..."** = bot found fix incomplete

### Step 3: Categorize findings

| Pattern | Indicator | Action |
|---------|-----------|--------|
| **Recurring root cause** | Same file/area, related issues across batches | Address root cause, not symptoms |
| **Incomplete parity** | "also needs X" after fixing Y | Audit all parallel locations |
| **Fix creates new issue** | "Fresh evidence after the prior fix" | Scope reduction or comprehensive sweep |
| **Grep/validation fragility** | Edge cases in string matching | Replace fragile validation with execution-time checks |
| **Genuine new issues** | Unrelated areas, different concerns | Fix individually |

### Step 4: Recommend action

Based on analysis, recommend one of:

1. **Continue fixing** - Issues are genuinely independent, no loop
2. **Comprehensive sweep** - Root cause identified, fix all instances at once
3. **Scope reduction** - Validation is inherently fragile, remove it and rely on execution-time errors
4. **Document and merge** - Known limitations acceptable for current phase

## Report format

```markdown
## Review Loop Analysis: PR #<number>

### Timeline
| Date | New Threads | Authors | Key Files |
|------|-------------|---------|-----------|
| ... | ... | ... | ... |

### Pattern detected: <pattern-name>

<evidence>

### Root cause
<description>

### Recommendation: <action>

<reasoning>
```

## Example output

```markdown
## Review Loop Analysis: PR #66

### Timeline
| Date | New Threads | Authors | Key Files |
|------|-------------|---------|-----------|
| Sep 14 | 36 | coderabbitai, chatgpt-codex | steps.yaml |
| Sep 15 | 73 | coderabbitai, chatgpt-codex | steps.yaml |
| Sep 17 | 30 | coderabbitai, chatgpt-codex | steps.yaml |
| Sep 18 | 9 | chatgpt-codex | steps.yaml |

### Pattern detected: Grep/validation fragility

Evidence:
- 90% of findings target `.ai-rulez/skills/infra-copilot/references/steps.yaml`
- Recurring theme: "greps match comments", "inline comments", "yq fallback"
- Multiple "Fresh evidence after the prior fix" phrases

### Root cause
Shell-based YAML validation (grep/sed/yq) has inherent edge cases.
Each fix addresses one edge case but exposes another.

### Recommendation: Scope reduction

Remove fragile static validation. Phase 4 runs actual workflows -
if misconfigured, terraform fails with clear errors. Real errors
beat predicted errors.
```

## Integration

Invoke early in a PR review cycle:
```
/investigate-reviews PR#66
```

Or when you notice the pattern forming:
```
User: "We've been fixing review comments for 3 days and they keep coming"
Agent: Let me run /investigate-reviews to see if we're in a loop.
```
