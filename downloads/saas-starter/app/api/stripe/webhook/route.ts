import { headers } from 'next/headers'
import { NextResponse } from 'next/server'
import Stripe from 'stripe'
import { prisma } from '@/lib/prisma'

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2023-10-16',
})

const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET!

export async function POST(req: Request) {
  const body = await req.text()
  const signature = headers().get('stripe-signature')!

  let event: Stripe.Event

  try {
    event = stripe.webhooks.constructEvent(body, signature, webhookSecret)
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 400 })
  }

  const session = event.data.object as Stripe.Checkout.Session

  switch (event.type) {
    case 'checkout.session.completed':
      // Handle successful checkout
      const subscription = await stripe.subscriptions.retrieve(
        session.subscription as string
      )

      await prisma.subscription.create({
        data: {
          userId: session.client_reference_id!,
          stripeCustomerId: session.customer as string,
          stripeSubscriptionId: subscription.id,
          stripePriceId: subscription.items.data[0].price.id,
          stripeCurrentPeriodEnd: new Date(subscription.current_period_end * 1000),
          status: subscription.status,
        },
      })
      break

    case 'invoice.payment_succeeded':
      // Handle successful payment
      const invoice = event.data.object as Stripe.Invoice

      await prisma.subscription.update({
        where: { stripeSubscriptionId: invoice.subscription as string },
        data: {
          stripePriceId: invoice.lines.data[0].price?.id!,
          stripeCurrentPeriodEnd: new Date((invoice.lines.data[0].period.end) * 1000),
          status: 'active',
        },
      })
      break

    case 'customer.subscription.deleted':
      // Handle subscription cancellation
      await prisma.subscription.update({
        where: { stripeSubscriptionId: session.id },
        data: { status: 'canceled' },
      })
      break
  }

  return NextResponse.json({ received: true })
}
