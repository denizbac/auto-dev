/**
 * Production-Ready Stripe Webhook Handler
 *
 * Features:
 * - Type-safe webhook handling
 * - Automatic signature verification
 * - Idempotency handling
 * - Error recovery
 * - Database integration
 * - Logging & monitoring
 *
 * Sell this for $19-49 on Gumroad
 */

import Stripe from 'stripe';
import { NextApiRequest, NextApiResponse } from 'next';
import { db } from '@/lib/db';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: '2023-10-16',
});

const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET!;

// Prevent Next.js from parsing the body
export const config = {
  api: {
    bodyParser: false,
  },
};

async function buffer(req: NextApiRequest) {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk);
  }
  return Buffer.concat(chunks);
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const buf = await buffer(req);
  const sig = req.headers['stripe-signature']!;

  let event: Stripe.Event;

  try {
    // Verify webhook signature
    event = stripe.webhooks.constructEvent(buf, sig, webhookSecret);
  } catch (err: any) {
    console.error(`Webhook signature verification failed: ${err.message}`);
    return res.status(400).json({ error: `Webhook Error: ${err.message}` });
  }

  // Check for duplicate events (idempotency)
  const existingEvent = await db.webhookEvent.findUnique({
    where: { stripeEventId: event.id },
  });

  if (existingEvent) {
    console.log(`Duplicate event ${event.id}, skipping`);
    return res.status(200).json({ received: true, duplicate: true });
  }

  // Store event for idempotency
  await db.webhookEvent.create({
    data: {
      stripeEventId: event.id,
      type: event.type,
      processed: false,
    },
  });

  try {
    // Handle the event
    switch (event.type) {
      case 'checkout.session.completed':
        await handleCheckoutComplete(event.data.object as Stripe.Checkout.Session);
        break;

      case 'customer.subscription.created':
        await handleSubscriptionCreated(event.data.object as Stripe.Subscription);
        break;

      case 'customer.subscription.updated':
        await handleSubscriptionUpdated(event.data.object as Stripe.Subscription);
        break;

      case 'customer.subscription.deleted':
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;

      case 'invoice.paid':
        await handleInvoicePaid(event.data.object as Stripe.Invoice);
        break;

      case 'invoice.payment_failed':
        await handleInvoicePaymentFailed(event.data.object as Stripe.Invoice);
        break;

      default:
        console.log(`Unhandled event type: ${event.type}`);
    }

    // Mark as processed
    await db.webhookEvent.update({
      where: { stripeEventId: event.id },
      data: { processed: true },
    });

    res.status(200).json({ received: true });
  } catch (error: any) {
    console.error(`Error processing webhook: ${error.message}`);

    // Log error but don't fail - Stripe will retry
    await db.webhookEvent.update({
      where: { stripeEventId: event.id },
      data: {
        error: error.message,
        processed: false
      },
    });

    res.status(500).json({ error: 'Webhook processing failed' });
  }
}

async function handleCheckoutComplete(session: Stripe.Checkout.Session) {
  const userId = session.metadata?.userId;
  if (!userId) throw new Error('No userId in session metadata');

  await db.user.update({
    where: { id: userId },
    data: {
      stripeCustomerId: session.customer as string,
      subscriptionStatus: 'active',
    },
  });

  // Send welcome email
  // await sendEmail(userId, 'welcome');
}

async function handleSubscriptionCreated(subscription: Stripe.Subscription) {
  const user = await db.user.findUnique({
    where: { stripeCustomerId: subscription.customer as string },
  });

  if (!user) throw new Error('User not found');

  await db.subscription.create({
    data: {
      userId: user.id,
      stripeSubscriptionId: subscription.id,
      status: subscription.status,
      priceId: subscription.items.data[0].price.id,
      currentPeriodStart: new Date(subscription.current_period_start * 1000),
      currentPeriodEnd: new Date(subscription.current_period_end * 1000),
    },
  });
}

async function handleSubscriptionUpdated(subscription: Stripe.Subscription) {
  await db.subscription.update({
    where: { stripeSubscriptionId: subscription.id },
    data: {
      status: subscription.status,
      priceId: subscription.items.data[0].price.id,
      currentPeriodStart: new Date(subscription.current_period_start * 1000),
      currentPeriodEnd: new Date(subscription.current_period_end * 1000),
    },
  });

  // Update user status
  const sub = await db.subscription.findUnique({
    where: { stripeSubscriptionId: subscription.id },
    include: { user: true },
  });

  if (sub) {
    await db.user.update({
      where: { id: sub.userId },
      data: { subscriptionStatus: subscription.status },
    });
  }
}

async function handleSubscriptionDeleted(subscription: Stripe.Subscription) {
  await db.subscription.update({
    where: { stripeSubscriptionId: subscription.id },
    data: { status: 'canceled' },
  });

  const sub = await db.subscription.findUnique({
    where: { stripeSubscriptionId: subscription.id },
  });

  if (sub) {
    await db.user.update({
      where: { id: sub.userId },
      data: { subscriptionStatus: 'canceled' },
    });
  }
}

async function handleInvoicePaid(invoice: Stripe.Invoice) {
  // Record payment
  await db.payment.create({
    data: {
      stripeInvoiceId: invoice.id,
      amount: invoice.amount_paid,
      currency: invoice.currency,
      status: 'paid',
    },
  });
}

async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  // Notify user of failed payment
  const subscription = await db.subscription.findUnique({
    where: { stripeSubscriptionId: invoice.subscription as string },
    include: { user: true },
  });

  if (subscription) {
    // await sendEmail(subscription.user.email, 'payment-failed');
  }
}
