# SaaS Starter Kit 🚀

**Production-ready Next.js 14 SaaS template with authentication, payments, and database.**

Stop wasting weeks on boilerplate. Start building features that matter.

## ✨ What's Included

- ✅ **Authentication** - NextAuth.js with Google, GitHub, and email
- ✅ **Payments** - Stripe Checkout & subscription management
- ✅ **Database** - Prisma ORM with PostgreSQL
- ✅ **UI Components** - Beautiful, reusable React components
- ✅ **Styling** - Tailwind CSS with responsive design
- ✅ **TypeScript** - Full type safety
- ✅ **API Routes** - Checkout, webhooks, customer portal
- ✅ **Email** - Resend integration for transactional emails

## 🎯 Perfect For

- SaaS applications
- Membership sites
- Subscription products
- MVP launches
- Side projects

## 🚀 Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/saas-starter-kit
cd saas-starter-kit
npm install
```

### 2. Set Up Environment Variables

Copy `.env.example` to `.env.local`:

```bash
cp .env.example .env.local
```

Fill in your credentials:

```env
# Database
DATABASE_URL="postgresql://user:password@localhost:5432/saas"

# NextAuth
NEXTAUTH_URL="http://localhost:3000"
NEXTAUTH_SECRET="your-secret-here"  # Generate with: openssl rand -base64 32

# OAuth Providers
GOOGLE_CLIENT_ID="your-google-client-id"
GOOGLE_CLIENT_SECRET="your-google-client-secret"
GITHUB_CLIENT_ID="your-github-client-id"
GITHUB_CLIENT_SECRET="your-github-client-secret"

# Stripe
STRIPE_SECRET_KEY="sk_test_..."
STRIPE_WEBHOOK_SECRET="whsec_..."
STRIPE_PRO_MONTHLY_PRICE_ID="price_..."

# Email
RESEND_API_KEY="re_..."
```

### 3. Set Up Database

```bash
npm run db:push
```

### 4. Run Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## 📁 Project Structure

```
├── app/
│   ├── api/auth/          # NextAuth
│   ├── api/stripe/        # Stripe routes
│   ├── dashboard/         # Protected dashboard
│   ├── pricing/           # Pricing page
│   └── page.tsx           # Landing page
├── components/            # Reusable UI components
├── lib/                   # Utilities
├── prisma/schema.prisma   # Database schema
```

## 💳 Pricing

**This is a template you can customize and sell:**

- Free tier for users to try
- Pro ($29/mo) for full features
- Team ($99/mo) for collaboration

Edit pricing in `app/pricing/page.tsx`

## 🚢 Deployment

Deploy to Vercel in one click:

```bash
vercel
```

Works on: Netlify, Railway, DigitalOcean, AWS

## 📈 Monetization

**Sell this template on:**
- Gumroad ($49-199)
- GitHub Sponsors
- Your own site

Potential: $490-5,970/month with 10-30 sales

## 🛟 Support

- [Next.js Docs](https://nextjs.org/docs)
- [Stripe Docs](https://stripe.com/docs)
- [Prisma Docs](https://prisma.io/docs)

## 📄 License

MIT - Use for personal or commercial projects

---

**Ready to launch?** Clone, configure, deploy. Ship your SaaS this weekend.

⭐ Star if this saved you time!
