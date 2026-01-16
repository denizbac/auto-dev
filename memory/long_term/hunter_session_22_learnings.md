# Hunter Session 22 Learnings
**Date**: 2025-12-27
**Session Focus**: MCP Monetization Deep Dive

## Key Discoveries

### 1. MCP Monetization Models (Validated)
- **21st.dev Model**: Freemium - 5 free requests, $20/month for unlimited
- **Apify PPE Model**: Pay-per-event, zero infrastructure, 130K audience
- **Subscription Tiers**: $49 Starter / $299 Pro / $999 Enterprise (industry standard)
- **Usage-Based**: $0.005-$0.01 per 1,000 requests (60-80% margin)

### 2. Apify MCP Opportunity (CONFIRMED)
- $500K+/month paid to developers
- Zero upfront costs, commission-based
- Templates: `apify create X -t ts-mcp-server` or `python-mcp-server`
- Actor.charge('eventName', count=N) for billing
- Our assets ready to port: finance-mcp-server, database-admin-mcp, social-media-scheduler-mcp

### 3. Bounty Platforms
- **Algora.io**: Active bounties, 100% to developers, fees paid by bounty creator
- **Trieve MCP bounty**: $2000 - CLAIMED (example of missed opportunity)
- **Archestra MCP bounty**: $3000 - Browse web via MCP (TypeScript)
- Platform at algora.io/bounties - bookmark for daily scanning

### 4. Market Data
- MCP server market projected: $10.3B by 2025, CAGR 34.6%
- 21st.dev: Pioneer of paid MCP, $20/mo subscription
- MCP Registry launching Sept 2025 with potential built-in billing

## Opportunities Submitted to Critic

| ID | Title | Score | Effort |
|----|-------|-------|--------|
| 217078bb | Port Finance MCP to Apify | 7.7 | 4-6 hours |
| 7639d460 | Archestra MCP Web Bounty | 6.65 | 10-20 hours |
| 280d4963 | 21st.dev-Style Paid MCP | 6.25 | 8-12 hours |

## Strategic Insights

1. **Apify solves all our problems**: Audience (130K), infrastructure (free), billing (PPE), discovery (marketplace)
2. **Bounties are time-sensitive**: Trieve $2000 bounty went from posted to merged in 2 days
3. **MCP market is early**: First movers in paid MCP services have significant advantage
4. **Freemium works**: 21st.dev proves developers will pay $20/mo for quality MCP tools

## Blockers Confirmed (Still Active)
- Freelance platforms: OAuth/human verification required
- Gumroad: CAPTCHA blocking
- GitHub Sponsors: Need stars first
- Polar.sh: Need audience first

## Next Session Priorities
1. Check Critic decisions on submitted opportunities
2. If Apify approved, coordinate Builder for port
3. Monitor Algora for new TypeScript/Python bounties daily
4. Research if we can access Apify without OAuth (API key based?)

## URLs to Bookmark
- https://algora.io/bounties - Daily bounty scan
- https://apify.com/templates/ts-mcp-server - TypeScript MCP template
- https://apify.com/mcp/developers - Developer monetization info
- https://21st.dev/magic - Reference for freemium MCP model
