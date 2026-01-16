import { redirect } from 'next/navigation'
import { getServerSession } from 'next-auth'
import { authOptions } from '../api/auth/[...nextauth]/route'
import { prisma } from '@/lib/prisma'

export default async function Dashboard() {
  const session = await getServerSession(authOptions)

  if (!session?.user?.email) {
    redirect('/api/auth/signin')
  }

  const user = await prisma.user.findUnique({
    where: { email: session.user.email },
    include: { subscription: true }
  })

  const isPro = user?.subscription?.status === 'active'

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
          <h1 className="text-xl font-bold text-gray-900">Dashboard</h1>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-600">{session.user.email}</span>
            <a href="/api/auth/signout" className="text-sm text-red-600 hover:underline">
              Sign Out
            </a>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-gray-900 mb-2">
            Welcome back, {user?.name || 'there'}!
          </h2>
          <p className="text-gray-600">
            {isPro ? '✨ Pro member' : 'Free tier'}
          </p>
        </div>

        {!isPro && (
          <div className="bg-gradient-to-r from-purple-600 to-blue-600 rounded-xl p-8 mb-8 text-white">
            <h3 className="text-2xl font-bold mb-2">Upgrade to Pro</h3>
            <p className="mb-4 text-purple-100">
              Get access to premium features, priority support, and exclusive content.
            </p>
            <a
              href="/pricing"
              className="inline-block bg-white text-purple-600 px-6 py-3 rounded-lg font-semibold hover:bg-gray-100"
            >
              View Pricing
            </a>
          </div>
        )}

        <div className="grid md:grid-cols-3 gap-6">
          <StatCard
            title="Projects"
            value="0"
            description="Create your first project"
          />
          <StatCard
            title="API Calls"
            value="0"
            description="No usage this month"
          />
          <StatCard
            title="Storage Used"
            value="0 MB"
            description="Unlimited with Pro"
            highlight={isPro}
          />
        </div>

        <div className="mt-8 bg-white rounded-xl shadow-sm p-6">
          <h3 className="text-xl font-bold mb-4">Recent Activity</h3>
          <div className="text-center py-12 text-gray-500">
            <p>No activity yet. Start building to see your history here.</p>
          </div>
        </div>

        {isPro && (
          <div className="mt-8 bg-white rounded-xl shadow-sm p-6">
            <h3 className="text-xl font-bold mb-4">Subscription Details</h3>
            <div className="space-y-2 text-sm">
              <p><span className="font-semibold">Status:</span> Active</p>
              <p><span className="font-semibold">Plan:</span> Pro</p>
              <p>
                <span className="font-semibold">Renews:</span>{' '}
                {user.subscription?.stripeCurrentPeriodEnd
                  ? new Date(user.subscription.stripeCurrentPeriodEnd).toLocaleDateString()
                  : 'N/A'
                }
              </p>
              <a
                href="/api/stripe/portal"
                className="inline-block mt-4 text-purple-600 hover:underline"
              >
                Manage Subscription →
              </a>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function StatCard({
  title,
  value,
  description,
  highlight
}: {
  title: string
  value: string
  description: string
  highlight?: boolean
}) {
  return (
    <div className={`bg-white rounded-xl shadow-sm p-6 ${highlight ? 'ring-2 ring-purple-600' : ''}`}>
      <h4 className="text-sm font-semibold text-gray-600 mb-2">{title}</h4>
      <p className="text-3xl font-bold text-gray-900 mb-1">{value}</p>
      <p className="text-sm text-gray-500">{description}</p>
    </div>
  )
}
