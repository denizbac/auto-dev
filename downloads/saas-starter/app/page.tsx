import Link from 'next/link'

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-purple-600 to-blue-600">
      <nav className="p-6 flex justify-between items-center max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-white">SaaS Starter</h1>
        <div className="space-x-4">
          <Link href="/login" className="text-white hover:underline">Login</Link>
          <Link href="/signup" className="bg-white text-purple-600 px-4 py-2 rounded-lg font-semibold hover:bg-gray-100">
            Get Started
          </Link>
        </div>
      </nav>

      <div className="max-w-4xl mx-auto text-center px-6 py-20">
        <h2 className="text-5xl font-bold text-white mb-6">
          Launch Your SaaS in Hours
        </h2>
        <p className="text-xl text-purple-100 mb-12">
          Production-ready starter with authentication, payments, database, and more.
          Skip weeks of setup and start building features that matter.
        </p>

        <div className="grid md:grid-cols-3 gap-8 mt-16">
          <Feature
            title="🔐 Auth Built-In"
            description="NextAuth with Google, GitHub, and email login ready to go"
          />
          <Feature
            title="💳 Stripe Payments"
            description="Subscription management and webhooks configured"
          />
          <Feature
            title="🗄️ Database Ready"
            description="Prisma ORM with PostgreSQL, migrations included"
          />
          <Feature
            title="🎨 Beautiful UI"
            description="Tailwind CSS with dark mode and responsive design"
          />
          <Feature
            title="📧 Email System"
            description="Transactional emails with Resend integration"
          />
          <Feature
            title="⚡ Fast & Modern"
            description="Next.js 14, TypeScript, and best practices"
          />
        </div>

        <div className="mt-16 bg-white rounded-2xl p-8 text-left">
          <h3 className="text-2xl font-bold mb-4">Quick Start</h3>
          <pre className="bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto">
{`git clone https://github.com/yourusername/saas-starter
cd saas-starter
npm install
cp .env.example .env.local
npm run dev`}
          </pre>
          <p className="mt-4 text-gray-600">
            Free to use. <span className="font-semibold">Pro version ($49)</span> includes video tutorials,
            priority support, and Discord access.
          </p>
          <button className="mt-4 bg-purple-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-purple-700">
            Get Pro Access - $49
          </button>
        </div>
      </div>
    </main>
  )
}

function Feature({ title, description }: { title: string; description: string }) {
  return (
    <div className="bg-white/10 backdrop-blur-lg rounded-xl p-6 text-white">
      <h3 className="text-xl font-semibold mb-2">{title}</h3>
      <p className="text-purple-100">{description}</p>
    </div>
  )
}
