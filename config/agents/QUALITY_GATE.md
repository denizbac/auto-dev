# Quality Gate: Mandatory Review & Testing Before Publishing

## RULE: No publishing without code review AND passing tests!

### Publishing Workflow (MANDATORY)

```
Builder → Reviewer → Tester → Human Approval → Publisher
```

1. **Builder** creates product → creates `code_review` task for Reviewer
2. **Reviewer** reviews code → creates REVIEW_REPORT.md
   - If PASS → creates `test_product` task for Tester
   - If FAIL → creates `fix_product` task for Builder
3. **Tester** validates product (THREE phases) → creates TEST_REPORT.md
   - Phase 1: Build verification (compilation, unit tests)
   - Phase 2: Functional testing (actually USE the product)
   - Phase 3: Customer experience (docs, install time, "would I pay?")
   - If PASS → submits approval request (human approval queue)
   - If FAIL → creates `fix_product` task for Builder
4. **Human** approves → creates `publish` task for Publisher
5. **Publisher** verifies REVIEW_REPORT.md + TEST_REPORT.md + approval_id, then publishes

### Before Publishing, Check:

```bash
# Check if code review exists and passed
cat /autonomous-claude/data/projects/PRODUCT_NAME/REVIEW_REPORT.md | grep -i "status\|verdict"
# Must see: Status: APPROVED or Verdict: APPROVED

# Check if test exists and passed
cat /autonomous-claude/data/projects/PRODUCT_NAME/TEST_REPORT.md | grep -i status
# Must see: Status: PASS

# If either is FAIL or missing → do not publish!
```

### Publisher Checklist

Before running `git push` or `npm publish`:
- [ ] REVIEW_REPORT.md exists with Status: APPROVED
- [ ] TEST_REPORT.md exists with Status: PASS
- [ ] TEST_REPORT.md includes Functional Tests section (not just build verification)
- [ ] Human approval received (for external platforms)
- [ ] `publish` task has valid `approval_id` in payload
- [ ] Verified approval_id is valid via orchestrator.is_approved()
- [ ] Rate limiting delay applied (30-120s for GitHub, 60-180s for npm)

If any check fails, create appropriate task instead of publishing.

### ⚠️ Account Protection (CRITICAL)

**The cybeleri GitHub account was flagged for bot activity.** To prevent suspension:

1. **Verify approval_id** before ANY publish command
2. **Add random delays** (30-120s) between ALL platform operations
3. **Daily limits**: Max 3 GitHub repos, 5 npm packages, 2 Gumroad products per day
4. **Never skip verification** - even for "quick" publishes

See `/autonomous-claude/config/settings.yaml` for rate_limits configuration.

## 🚫 PROHIBITED (Blocks the Whole Pipeline)

- **Bounty work** - Critic will block, Builder must refuse
- **Forking/cloning external repos** - We create original products only
- **External contributions** - No PRs to other projects
- **Self-testing by Builder** - Tester MUST create TEST_REPORT.md
