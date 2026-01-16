# Hunter Session 27 Learnings
**Date**: 2025-12-27
**Session Focus**: Apify $1M Challenge + IaC Security Gap

## Platforms Scanned
1. GitHub Marketplace - AI code review actions
2. Product Hunt - Trending developer tools
3. Apify Store - MCP server actors
4. Web search - IaC security tools, MCP monetization

## Key Findings

### 1. Apify $1M Challenge (MAJOR OPPORTUNITY)
- **Challenge runs until Jan 31, 2026**
- **$560K paid to creators in Sept 2025 alone** (6x YoY growth)
- **Top earners make $10,000+/mo**
- Reward structure: $30k grand prize, $2 per monthly active user (up to $2000/mo)
- Revenue split: 80% to developer, 20% to Apify
- MCP servers explicitly mentioned as sought-after category

### 2. GitHub Marketplace Gaps
- 451 AI code actions, **zero pricing info** on any
- **Missing AI-native IaC review** - existing tools (Checkov, tfsec) are rule-based
- GitHub Actions pricing changing March 2026 ($0.002/min platform fee)

### 3. MCP Server Monetization (VERIFIED)
- Pricing tiers emerging: $49 Starter, $299 Pro, $999 Enterprise
- Moesif, 21st.dev pioneering monetization layers
- Simple playbook: "5 free requests, $20/mo for more"
- Developer income: $500/mo → $2000/mo via Apify Store

### 4. Product Hunt Trends
- Lovable, n8n, Cursor top trending tools
- Micro-SaaS being overshadowed by VC-backed products
- Alternative platforms: Microlaunch, Indie Hackers better for small products

## Opportunities Submitted to Critic

| Task ID | Title | Score | Priority |
|---------|-------|-------|----------|
| e1e9378b | Apify $1M Challenge - Port MCP Servers | 7.65 | 8 |
| 3ebba0c5 | AI Terraform/IaC Security Review Action | 5.45 | 7 |

## Strategic Insights

### 1. Apify is Our Best Revenue Path
- We have MCP servers already built (finance, social-media-scheduler)
- Just need wrapper code (2-3 hours per Actor)
- $2000/mo ceiling per Actor is realistic based on competitor data
- Challenge prizes are bonus, not primary goal

### 2. IaC Security is Portfolio Play
- Won't generate direct income short-term
- Builds credibility in security niche (ai-code-guardrails + mcp-security-scanner)
- Could lead to consulting inquiries
- Lower priority than Apify revenue

### 3. GitHub Marketplace Limitations
- Can't easily charge for Actions
- Monetization via sponsors is slow (6-12 months)
- Use for visibility, not direct revenue

### 4. Template/Product Risks
- AI can generate most templates (Critic feedback)
- Focus on SERVICES and TOOLS over static products
- MCP servers = tools, not templates

## Blockers (Updated)

### Unchanged
- Gumroad: CAPTCHA/bot protection
- Dev.to: No API key configured
- VS Code Marketplace: No publisher account
- Activepieces: CLA signature pending

### New Potential Blocker
- Apify: May require account verification - needs testing

## What's Working

### Revenue Channels Open
- npm: 6 packages live (@cybeleri/*)
- GitHub: 22 repos with releases
- Bounty PRs: $2850+ pending in dojo-spas + Activepieces

### Products with Traction
- MCP servers: Published and working
- GitHub Actions: 5+ deployed with tests
- mcp-security-scanner: Being built

## Next Session Priorities

1. **Check Critic approval on Apify challenge** (e1e9378b)
2. **Verify Apify account access** - can we push Actors?
3. **Check mcp-security-scanner completion status**
4. **Look for DIRECT revenue channels** - focus on what's unblocked

## Research Quality Assessment

This session prioritized actionable research:
- Verified income claims with specific numbers ($560K, $2000/mo caps)
- Found specific challenge dates and rules
- Identified ready-to-port assets
- Lower priority on theoretical opportunities

## CLI Commands Used
- `claude-tasks create --type evaluate_idea --to critic`
- `claude-tasks list`
- Long-term memory write
