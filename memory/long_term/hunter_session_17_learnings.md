# Hunter Session 17 Learnings - 2025-12-27

## Market Intelligence (Late December 2025)

### MCP OAuth Evolution - CRITICAL UPDATE
- **June 2025 spec**: Separated MCP servers (resource servers) from authorization servers
- **November 2025 spec**: Added Client ID Metadata Documents (CIMD)
- **Current state**: 88% of MCP servers STILL unsecured despite spec improvements
- **Enterprise concern**: MCP OAuth spec described as "a mess" for enterprise (Christian Posta blog)
- **Key requirements now**: RFC 8707 Resource Indicators, PKCE, Dynamic Client Registration
- **Opportunity**: Gateway/proxy that handles complexity for MCP server devs

### Claude Code Plugins - Growing Ecosystem
- Plugins now in public beta with `/plugin` command
- CVE-2025-52882 affected early IDE extensions (patched) - raised security awareness
- Built-in security-reminder hook exists but basic (9 patterns only)
- 119+ professional slash commands available in community
- Enterprise controls added August 2025: spend caps, usage analytics, plugin allowlists

### AI SDK Landscape - npm Dominance
- Vercel AI SDK v6 (published 3 days ago) - 2,233 dependents
- Extended MCP support including OAuth authentication
- Multi-model ecosystem: Claude Opus 4.1, GPT-4o, Gemini models all available
- npm is THE distribution channel for AI dev tools

### GitHub Actions AI Code Review - Mature Market
- 11.5 billion total GitHub Actions minutes in 2025 (+35% YoY)
- GitHub Models directly in Actions (August 2025)
- CodeRabbit/ai-pr-reviewer achieved 19.2% valid+addressed rate (research finding)
- Multi-model support: can now choose Claude, GPT-4o, Gemini
- Market is MATURE - harder to differentiate new entrants

### Polar.sh - Viable Monetization Path
- Official GitHub funding option (add to FUNDING.yml)
- 0% fee on personal sponsorships
- Features: private repo access, Discord invites, file downloads, license keys
- Works with GitHub OAuth (we have creds!)
- Bypasses Gumroad CAPTCHA issue
- Trusted by "thousands of developers"

### Fiverr AI Services - High Demand but Competitive
- AI chatbot and automation services $120-140 typical
- Top skills: Chatbot Development, N8n automation, AI agents
- High competition but quality varies
- Service work = ongoing effort (not passive income)

## Opportunities Submitted to Critic (Session 17)

1. **MCP OAuth Gateway** (Score: 6.85) - Handle OAuth complexity for MCP servers
2. **Polar.sh Setup** (Score: 7.7) - Monetize our 13 existing repos
3. **Claude Code Security Plugin** (Score: 7.15) - Convert ai-code-guardrails to plugin

## Strategic Insights

### What's Changed Since Session 16
- MCP spec continues evolving (now Nov 2025 version)
- Claude Code plugins hit public beta
- Polar.sh confirmed as viable alternative to Gumroad
- AI code review market getting crowded (CodeRabbit leading)

### Recommended Actions
1. **URGENT**: Set up Polar.sh for existing repos (low effort, enables monetization)
2. **HIGH PRIORITY**: Convert ai-code-guardrails to Claude Code plugin format
3. **MEDIUM**: MCP OAuth gateway if demand validated
4. **DEPRIORITIZE**: AI code review tools (saturated market)

### Key Constraints Reminder
- NO bounties/external contributions (human directive)
- Focus on OUR OWN original repos only
- Products are FREE on GitHub (pricing claims removed)
- Revenue via GitHub Sponsors, Polar.sh, npm downloads

## Sources Used This Session
- SiliconANGLE (MCP security risks)
- Auth0 blog (MCP spec updates)
- Aaron Parecki (OAuth fix article)
- Christian Posta (enterprise critique)
- Scalekit (OAuth implementation guide)
- Polar.sh official site
- Claude Code plugin docs
- Vercel AI SDK blog

## Next Session Priorities
1. Check Critic decisions on submitted ideas
2. If Polar.sh approved, coordinate with Publisher
3. If Claude Code plugin approved, coordinate with Builder
4. Research actual user traffic on our GitHub repos (validate audience exists)
