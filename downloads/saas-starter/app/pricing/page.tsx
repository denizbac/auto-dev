import { redirect } from 'next/navigation'
import { getServerSession } from 'next-auth'
import { authOptions } from '../api/auth/[...nextauth]/route'

export default async function Pricing() {
  const session = await getServerSession(authOptions)

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
          <a href="/" className="text-xl font-bold text-gray-900">SaaS Starter</a>
          <div className="flex items-center gap-4">
            {session ? (
              <>
                <a href="/dashboard" className="text-sm text-gray-600 hover:underline">Dashboard</a>
                <a href="/api/auth/signout" className="text-sm text-red-600 hover:underline">Sign Out</a>
              </>
            ) : (
              <>
                <a href="/api/auth/signin" className="text-sm text-gray-600 hover:underline">Sign In</a>
                <a
                  href="/api/auth/signin"
                  className="bg-purple-600 text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-purple-700"
                >
                  Get Started
                </a>
              </>
            )}
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 py-16">
        <div className="text-center mb-16">
          <h1 className="text-4xl font-bold text-gray-900 mb-4">
            Simple, Transparent Pricing
          </h1>
          <p className="text-xl text-gray-600">
            Choose the plan that's right for you
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-8 max-w-6xl mx-auto">
          <PricingCard
            name="Free"
            price="$0"
            description="Perfect for getting started"
            features={[
              '5 projects',
              '1,000 API calls/month',
              'Community support',
              'Basic analytics',
              '1 GB storage'
            ]}
            cta="Get Started Free"
            ctaLink="/api/auth/signin"
            highlighted={false}
          />

          <PricingCard
            name="Pro"
            price="$29"
            priceSubtext="/month"
            description="For serious builders"
            features={[
              'Unlimited projects',
              '100,000 API calls/month',
              'Priority email support',
              'Advanced analytics',
              '50 GB storage',
              'Custom domain',
              'Early access to features'
            ]}
            cta="Upgrade to Pro"
            ctaLink={session ? "/api/stripe/checkout?plan=pro" : "/api/auth/signin"}
            highlighted={true}
          />

          <PricingCard
            name="Team"
            price="$99"
            priceSubtext="/month"
            description="For growing teams"
            features={[
              'Everything in Pro',
              'Unlimited API calls',
              '24/7 priority support',
              'Team collaboration',
              '500 GB storage',
              'SSO & Advanced security',
              'Dedicated account manager'
            ]}
            cta="Contact Sales"
            ctaLink="mailto:support@saas-starter.com"
            highlighted={false}
          />
        </div>

        <div className="mt-16 text-center">
          <h3 className="text-2xl font-bold text-gray-900 mb-4">
            Frequently Asked Questions
          </h3>
          <div className="max-w-3xl mx-auto text-left space-y-6">
            <FAQ
              question="Can I change my plan later?"
              answer="Yes! You can upgrade or downgrade your plan at any time. Changes take effect immediately."
            />
            <FAQ
              question="What payment methods do you accept?"
              answer="We accept all major credit cards via Stripe. All payments are secure and encrypted."
            />
            <FAQ
              question="Is there a refund policy?"
              answer="Yes, we offer a 14-day money-back guarantee. No questions asked."
            />
            <FAQ
              question="Do you offer discounts for annual billing?"
              answer="Yes! Save 20% when you pay annually. Contact sales for details."
            />
          </div>
        </div>
      </main>
    </div>
  )
}

function PricingCard({
  name,
  price,
  priceSubtext,
  description,
  features,
  cta,
  ctaLink,
  highlighted
}: {
  name: string
  price: string
  priceSubtext?: string
  description: string
  features: string[]
  cta: string
  ctaLink: string
  highlighted: boolean
}) {
  return (
    <div className={`bg-white rounded-2xl shadow-lg p-8 ${highlighted ? 'ring-2 ring-purple-600 relative' : ''}`}>
      {highlighted && (
        <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2">
          <span className="bg-purple-600 text-white px-4 py-1 rounded-full text-sm font-semibold">
            Most Popular
          </span>
        </div>
      )}

      <h3 className="text-2xl font-bold text-gray-900 mb-2">{name}</h3>
      <div className="mb-4">
        <span className="text-4xl font-bold text-gray-900">{price}</span>
        {priceSubtext && <span className="text-gray-600 ml-1">{priceSubtext}</span>}
      </div>
      <p className="text-gray-600 mb-6">{description}</p>

      <ul className="space-y-3 mb-8">
        {features.map((feature, idx) => (
          <li key={idx} className="flex items-start gap-2">
            <svg className="w-5 h-5 text-green-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/>
            </svg>
            <span className="text-gray-700">{feature}</span>
          </li>
        ))}
      </ul>

      <a
        href={ctaLink}
        className={`block w-full text-center py-3 px-6 rounded-lg font-semibold transition-colors ${
          highlighted
            ? 'bg-purple-600 text-white hover:bg-purple-700'
            : 'bg-gray-100 text-gray-900 hover:bg-gray-200'
        }`}
      >
        {cta}
      </a>
    </div>
  )
}

function FAQ({ question, answer }: { question: string; answer: string }) {
  return (
    <div className="bg-white rounded-lg p-6 shadow-sm">
      <h4 className="font-semibold text-gray-900 mb-2">{question}</h4>
      <p className="text-gray-600">{answer}</p>
    </div>
  )
}
