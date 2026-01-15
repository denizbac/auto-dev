import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/agents': 'Agents',
  '/repos': 'Repositories',
  '/tasks': 'Tasks',
  '/approvals': 'Approvals',
  '/settings': 'Settings',
}

export function Layout() {
  const location = useLocation()
  const title = pageTitles[location.pathname] || 'Auto-Dev'

  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header title={title} />
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
