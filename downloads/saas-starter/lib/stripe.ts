import Stripe from 'stripe'

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2024-12-18.acacia',
  typescript: true,
})

export const STRIPE_PLANS = {
  pro: {
    monthly: process.env.STRIPE_PRO_MONTHLY_PRICE_ID!,
    yearly: process.env.STRIPE_PRO_YEARLY_PRICE_ID!,
  },
  team: {
    monthly: process.env.STRIPE_TEAM_MONTHLY_PRICE_ID!,
    yearly: process.env.STRIPE_TEAM_YEARLY_PRICE_ID!,
  },
}
