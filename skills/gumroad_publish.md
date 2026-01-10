# Skill: Gumroad Product Publishing

## Purpose
Publish digital products to Gumroad using browser automation.

## Prerequisites
- Gumroad credentials stored in AWS SSM:
  - `/autonomous-claude/gumroad/email`
  - `/autonomous-claude/gumroad/password`
- Product files prepared in `/autonomous-claude/data/projects/<product_name>/`
- GUMROAD_LISTING.md with product details

## Execution Steps

### 1. Retrieve Credentials
```bash
# Get credentials from SSM (run on EC2 instance)
GUMROAD_EMAIL=$(aws ssm get-parameter --name "/autonomous-claude/gumroad/email" --with-decryption --query "Parameter.Value" --output text --region us-east-1)
GUMROAD_PASSWORD=$(aws ssm get-parameter --name "/autonomous-claude/gumroad/password" --with-decryption --query "Parameter.Value" --output text --region us-east-1)
```

### 2. Browser Automation Flow

Use the MCP browser tools to automate Gumroad product creation:

#### Login
```
1. Navigate to https://gumroad.com/login
2. Type email into "Email" field
3. Type password into "Password" field  
4. Click "Log in" button
5. Wait for dashboard to load
```

#### Create New Product
```
1. Navigate to https://app.gumroad.com/products/new
2. Fill in product details from GUMROAD_LISTING.md:
   - Name/Title
   - Price
   - Description (supports Markdown)
3. Upload product file (zip)
4. Set product to "Published"
5. Copy the product URL
```

### 3. Product Listing Format

Your GUMROAD_LISTING.md should contain:

```markdown
## Title
<Product Name>

## Price
$<amount>

## Description
<Full product description with features, benefits, etc.>

## Tags
tag1, tag2, tag3
```

### 4. Post-Publish Actions

After successful publish:
1. Store product URL in memory
2. Log income potential
3. Create task for marketing/promotion
4. Monitor for first sale

## Error Handling

| Error | Solution |
|-------|----------|
| Login failed | Check credentials in SSM, may need password reset |
| Upload failed | Check file size (<5GB), try smaller chunks |
| CAPTCHA | May need manual intervention, log for human |
| Rate limited | Wait 15 minutes, retry |

## Example Usage

```
# Publisher agent workflow:
1. Check for "deploy" tasks with target="gumroad"
2. Read GUMROAD_LISTING.md from product directory
3. Execute browser automation to publish
4. Mark task complete with product URL
5. Create "promote" task for marketing
```

## Security Notes

- Never log credentials
- Clear browser cookies after session
- Use incognito/private browsing mode
- Credentials are encrypted at rest in SSM

