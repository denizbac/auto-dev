# Test-Fix-Retest Loop

## The Loop (MANDATORY)



## Tester Actions

After testing, create ONE of these tasks:

### If PASS:
```bash
claude-tasks submit-approval \
  --name "PRODUCT_NAME" \
  --type "product" \
  --platform "gumroad|github|npm" \
  --description "Validated product ready for human approval" \
  --files "/auto-dev/data/projects/PRODUCT_NAME" \
  --from tester
```

### If FAIL:
```bash
claude-tasks create --type fix_product --to builder --priority 9 \
  --payload '{"product": "PRODUCT_NAME", "issues": ["issue1", "issue2"], "test_report": "PATH/TEST_REPORT.md"}'
```

## Builder Actions

After receiving fix_product task:
1. Read TEST_REPORT.md to understand issues
2. Fix all listed issues
3. Create NEW test_product task for Tester (retest!)

```bash
claude-tasks create --type test_product --to tester --priority 9 \
  --payload '{"product": "PRODUCT_NAME", "path": "/auto-dev/data/projects/PRODUCT_NAME", "retest": true}'
```

## Publisher Actions

Before publishing, verify:
1. TEST_REPORT.md exists
2. Status is PASS (not FAIL or NEEDS FIXES)
3. If not, reject and create test_product task

## Loop Continues Until PASS

The product keeps bouncing between Builder and Tester until all issues are fixed.
Only PASS status allows publishing.
