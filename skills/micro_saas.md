# Skill: Micro-SaaS Development

## Description
Build and deploy small, focused web applications that solve specific problems.
Deploy for free and monetize through various channels.

## When to Use
- Have identified a specific pain point
- Can build solution in < 4 hours
- Free hosting available (Vercel, Netlify, Cloudflare)

## Prerequisites
- GitHub account for deployment
- Stripe account (for payments)
- Domain (optional, use platform subdomain initially)

## Steps

### Step 1: Validate Idea
Before building, verify demand:
- Search Twitter/Reddit for people complaining about problem
- Check if paid alternatives exist (validates market)
- Estimate: Would 100 people pay $5/month for this?

Quick validation tools:
- Google Trends
- Product Hunt similar products
- Reddit keyword search

### Step 2: Build MVP
Keep it minimal:
```
/project
├── index.html       # Single page app
├── style.css        # Styling
├── app.js           # Core functionality
└── README.md        # Documentation
```

Tech stack options:
- **Simplest**: HTML + Tailwind + Vanilla JS
- **Interactive**: React/Vue + API
- **Full stack**: Next.js + Supabase (free tier)

### Step 3: Deploy
Using Vercel (recommended):
```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel --prod
```

Or Netlify:
```bash
# Drop folder in netlify.com/drop
# Or connect GitHub repo
```

### Step 4: Monetize
Options in order of simplicity:
1. **Donation button** (Buy Me a Coffee, Ko-fi)
2. **One-time payment** (Gumroad, LemonSqueezy)
3. **Subscription** (Stripe, Paddle)
4. **Ads** (Carbon Ads for dev tools)

### Step 5: Launch & Iterate
Launch checklist:
- [ ] Post on relevant subreddits
- [ ] Tweet with problem/solution hook
- [ ] Submit to Product Hunt
- [ ] Post in relevant Discord/Slack communities
- [ ] Hacker News "Show HN" (if novel)

## Success Criteria
- [ ] App deployed and accessible
- [ ] At least one monetization method active
- [ ] First user acquired
- [ ] First dollar earned

## Common Issues
| Issue | Solution |
|-------|----------|
| No traffic | Improve SEO, post in communities |
| No conversions | Simplify value prop, lower price |
| Technical issues | Check browser console, test mobile |
| Competitors appear | Focus on niche, improve UX |

## Income Potential
- Estimated $/hour: Variable ($0-1000+)
- Difficulty: Medium-High
- Token cost: ~5000-20000 per full build cycle

## Micro-SaaS Ideas (Validated)
1. **PDF tools** - merge, split, compress
2. **Image tools** - resize, compress, convert
3. **Text tools** - word count, diff, format
4. **Developer tools** - JSON formatter, regex tester
5. **Calculators** - specific niche calculations
6. **Converters** - units, currencies, timezones

## Notes
- Simple > Complex. Users want solutions, not features.
- One job, done well, beats Swiss army knife.
- Free tier can generate traffic; premium features for power users.
- Document everything for potential sale/acquisition.

