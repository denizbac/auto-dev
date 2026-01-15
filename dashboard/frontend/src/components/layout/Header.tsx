import { useQuery } from '@tanstack/react-query'
import { Activity, Bell } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { getAgentStatuses, getApprovals } from '@/lib/api'

interface HeaderProps {
  title: string
}

export function Header({ title }: HeaderProps) {
  const { data: agentData } = useQuery({
    queryKey: ['agent-statuses'],
    queryFn: getAgentStatuses,
  })

  const { data: approvalsData } = useQuery({
    queryKey: ['approvals'],
    queryFn: () => getApprovals('pending'),
  })

  const onlineAgents = agentData?.agents
    ? Object.values(agentData.agents).filter((a) => a.status === 'online').length
    : 0

  const pendingApprovals = approvalsData?.pending_count ?? 0

  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-card px-6">
      <h1 className="text-xl font-semibold">{title}</h1>

      <div className="flex items-center gap-4">
        {/* Status indicators */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <Activity className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Agents:</span>
            <Badge variant={onlineAgents > 0 ? 'success' : 'secondary'}>
              {onlineAgents} online
            </Badge>
          </div>
        </div>

        {/* Notifications */}
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-5 w-5" />
          {pendingApprovals > 0 && (
            <span className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-destructive text-destructive-foreground text-xs flex items-center justify-center">
              {pendingApprovals}
            </span>
          )}
        </Button>
      </div>
    </header>
  )
}
