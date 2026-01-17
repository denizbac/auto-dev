import { Routes, Route } from 'react-router-dom'
import { Layout } from '@/components/layout/Layout'
import Dashboard from '@/pages/Dashboard'
import Agents from '@/pages/Agents'
import Repositories from '@/pages/Repositories'
import Tasks from '@/pages/Tasks'
import Approvals from '@/pages/Approvals'
import Learnings from '@/pages/Learnings'
import Settings from '@/pages/Settings'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="agents" element={<Agents />} />
        <Route path="repos" element={<Repositories />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="learnings" element={<Learnings />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
