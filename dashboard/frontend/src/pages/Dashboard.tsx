import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  Zap,
  GitBranch,
  CheckCircle,
  Clock,
  Send,
  AlertTriangle,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  getStats,
  getAgentConfig,
  getAgentStatuses,
  getRepos,
  getTasks,
  getDiscussions,
  sendDirective,
  type Agent,
} from '@/lib/api'
import { formatNumber, formatDate } from '@/lib/utils'
import { useState } from 'react'

export default function Dashboard() {
  const [directive, setDirective] = useState('')

  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: getStats })
  const { data: agentConfig } = useQuery({ queryKey: ['agent-config'], queryFn: getAgentConfig })
  const { data: agentStatuses } = useQuery({ queryKey: ['agent-statuses'], queryFn: getAgentStatuses })
  const { data: repos } = useQuery({ queryKey: ['repos'], queryFn: getRepos })
  const { data: tasks } = useQuery({ queryKey: ['tasks'], queryFn: () => getTasks() })
  const { data: discussions } = useQuery({ queryKey: ['discussions'], queryFn: getDiscussions })

  const handleSendDirective = async () => {
    if (!directive.trim()) return
    await sendDirective(directive, 8)
    setDirective('')
  }

  const pendingTasks = tasks?.stats?.pending ?? 0
  const onlineAgents = agentStatuses?.agents
    ? Object.values(agentStatuses.agents).filter((a) => a.status === 'online' || a.status === 'idle').length
    : 0

  // Rate limit info
  const rateLimit = agentStatuses?.rate_limit
  const formatCountdown = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  return (
    <div className="space-y-6">
      {/* Rate Limit Banner */}
      {rateLimit?.limited && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-500/50 bg-amber-500/10 p-4 animate-pulse">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <div className="text-sm">
            <span className="font-semibold text-amber-500">
              {rateLimit.provider.charAt(0).toUpperCase() + rateLimit.provider.slice(1)}
            </span>
            {' '}rate limited. Resets in{' '}
            <span className="font-mono font-bold text-amber-400">
              {formatCountdown(rateLimit.remaining_seconds)}
            </span>
          </div>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Tokens Used (7d)</CardTitle>
            <Zap className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-400">
              {formatNumber(stats?.tokens?.total_7d ?? 0)}
            </div>
            <p className="text-xs text-muted-foreground">API usage</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Agents</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-purple-400">
              {onlineAgents} / {agentConfig?.agents?.length ?? 0}
            </div>
            <p className="text-xs text-muted-foreground">Currently running</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pending Tasks</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-orange-400">{pendingTasks}</div>
            <p className="text-xs text-muted-foreground">In queue</p>
          </CardContent>
        </Card>
      </div>

      {/* Quick Directive */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Quick Directive</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              placeholder="Send a directive to all agents..."
              value={directive}
              onChange={(e) => setDirective(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendDirective()}
            />
            <Button onClick={handleSendDirective}>
              <Send className="h-4 w-4 mr-2" />
              Send
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Agent Status Grid */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Agent Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3">
              {agentConfig?.agents?.map((agent: Agent) => {
                const status = agentStatuses?.agents?.[agent.id]
                const isOnline = status?.status === 'online'
                return (
                  <div
                    key={agent.id}
                    className="flex items-center gap-3 rounded-lg border border-border p-3"
                  >
                    <span className="text-xl">{agent.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{agent.name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {status?.current_task_id ? 'Working...' : 'Idle'}
                      </p>
                    </div>
                    <div
                      className={`h-2 w-2 rounded-full ${
                        isOnline ? 'bg-green-500' : 'bg-gray-500'
                      }`}
                    />
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>

        {/* Repositories */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <GitBranch className="h-4 w-4" />
              Repositories
            </CardTitle>
          </CardHeader>
          <CardContent>
            {repos?.repos?.length === 0 ? (
              <p className="text-sm text-muted-foreground">No repositories configured</p>
            ) : (
              <div className="space-y-3">
                {repos?.repos?.slice(0, 5).map((repo) => (
                  <div
                    key={repo.id}
                    className="flex items-center justify-between rounded-lg border border-border p-3"
                  >
                    <div>
                      <p className="text-sm font-medium">{repo.name}</p>
                      <p className="text-xs text-muted-foreground truncate max-w-[200px]">
                        {repo.gitlab_url}
                      </p>
                    </div>
                    <Badge variant={repo.autonomy_mode === 'full' ? 'success' : 'secondary'}>
                      {repo.autonomy_mode}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Activity Feed */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <CheckCircle className="h-4 w-4" />
            Recent Activity
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 max-h-[300px] overflow-y-auto">
            {discussions?.discussions?.slice(0, 10).map((discussion) => (
              <div key={discussion.id} className="flex gap-3 border-b border-border pb-3 last:border-0">
                <div className="h-8 w-8 rounded-full bg-secondary flex items-center justify-center text-xs font-medium">
                  {discussion.author.slice(0, 2).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{discussion.author}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatDate(discussion.created_at)}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground truncate">{discussion.content}</p>
                </div>
              </div>
            )) ?? (
              <p className="text-sm text-muted-foreground">No recent activity</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
