import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, Square, RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  getAgentConfig,
  getAgentStatuses,
  getAgentProviders,
  getAgentTasks,
  startAgent,
  stopAgent,
  startAllAgents,
  stopAllAgents,
  setAgentProvider,
  type Agent,
} from '@/lib/api'
import { formatNumber } from '@/lib/utils'

export default function Agents() {
  const queryClient = useQueryClient()

  const { data: agentConfig } = useQuery({ queryKey: ['agent-config'], queryFn: getAgentConfig })
  const { data: agentStatuses } = useQuery({ queryKey: ['agent-statuses'], queryFn: getAgentStatuses })
  const { data: agentProviders } = useQuery({ queryKey: ['agent-providers'], queryFn: getAgentProviders })
  const { data: agentTasks } = useQuery({ queryKey: ['agent-tasks'], queryFn: () => getAgentTasks() })

  const startMutation = useMutation({
    mutationFn: startAgent,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-statuses'] }),
  })

  const stopMutation = useMutation({
    mutationFn: stopAgent,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-statuses'] }),
  })

  const startAllMutation = useMutation({
    mutationFn: startAllAgents,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-statuses'] }),
  })

  const stopAllMutation = useMutation({
    mutationFn: stopAllAgents,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-statuses'] }),
  })

  const providerMutation = useMutation({
    mutationFn: ({ agentType, provider }: { agentType: string; provider: string }) =>
      setAgentProvider(agentType, provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-providers'] })
      queryClient.invalidateQueries({ queryKey: ['agent-statuses'] })
    },
  })

  const getProviderForAgent = (agentId: string) => {
    const provider = agentProviders?.providers?.find((p) => p.agent_id === agentId)
    return provider?.provider_override || provider?.active_provider || agentProviders?.default_provider || 'codex'
  }

  return (
    <div className="space-y-6">
      {/* Global Controls */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Global Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <Button
              onClick={() => startAllMutation.mutate()}
              disabled={startAllMutation.isPending}
            >
              <Play className="h-4 w-4 mr-2" />
              Start All
            </Button>
            <Button
              variant="destructive"
              onClick={() => stopAllMutation.mutate()}
              disabled={stopAllMutation.isPending}
            >
              <Square className="h-4 w-4 mr-2" />
              Stop All
            </Button>
            <Button
              variant="outline"
              onClick={() => queryClient.invalidateQueries()}
            >
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
            <div className="ml-auto text-sm text-muted-foreground">
              Default Provider:{' '}
              <Badge variant="outline">{agentProviders?.default_provider ?? 'codex'}</Badge>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Agent Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {agentConfig?.agents?.map((agent: Agent) => {
          const status = agentStatuses?.agents?.[agent.id]
          const agentStatus = status?.status
          const isEnabled = status?.enabled !== false
          // Agent is "running" if it's processing tasks (enabled + heartbeat)
          const isRunning = isEnabled && (agentStatus === 'online' || agentStatus === 'running' || agentStatus === 'working' || agentStatus === 'idle' || agentStatus === 'rate_limited')
          const taskSummary = agentTasks?.summary?.[agent.id]
          const currentProvider = getProviderForAgent(agent.id)

          const getStatusBadge = () => {
            // Handle both old and new status values
            switch (agentStatus) {
              case 'working':
                return { variant: 'success' as const, label: 'Working' }
              case 'running':
              case 'idle':
                return { variant: 'success' as const, label: 'Running' }
              case 'online':
                return { variant: 'success' as const, label: 'Online' }
              case 'rate_limited':
                return { variant: 'warning' as const, label: 'Rate Limited' }
              case 'paused':
                return { variant: 'warning' as const, label: 'Paused' }
              case 'disabled':
              case 'stopped':
                return { variant: 'secondary' as const, label: 'Disabled' }
              case 'starting':
                return { variant: 'outline' as const, label: 'Starting' }
              default:
                return { variant: 'secondary' as const, label: 'Offline' }
            }
          }
          const statusBadge = getStatusBadge()

          const cardBorderClass = statusBadge.variant === 'success' ? 'border-green-500/50' : statusBadge.variant === 'warning' ? 'border-yellow-500/50' : ''

          return (
            <Card key={agent.id} className={cardBorderClass}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-2xl">{agent.icon}</span>
                    <CardTitle className="text-base">{agent.name}</CardTitle>
                  </div>
                  <Badge variant={statusBadge.variant}>
                    {statusBadge.label}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-xs text-muted-foreground line-clamp-2">{agent.description}</p>

                {/* Stats */}
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <p className="text-muted-foreground">Completed</p>
                    <p className="font-medium">{taskSummary?.completed ?? 0}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Pending</p>
                    <p className="font-medium">{taskSummary?.pending ?? 0}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Tokens</p>
                    <p className="font-medium">{formatNumber(status?.tokens_used ?? 0)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Model</p>
                    <p className="font-medium">{agent.model}</p>
                  </div>
                </div>

                {/* Provider Select */}
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Provider</label>
                  <Select
                    value={currentProvider}
                    onValueChange={(value) =>
                      providerMutation.mutate({ agentType: agent.id, provider: value })
                    }
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="codex">Codex (OpenAI)</SelectItem>
                      <SelectItem value="claude">Claude (Anthropic)</SelectItem>
                      <SelectItem value="auto">Auto (Fallback)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Controls */}
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1"
                    onClick={() => startMutation.mutate(agent.id)}
                    disabled={isRunning || startMutation.isPending}
                  >
                    <Play className="h-3 w-3 mr-1" />
                    Start
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1"
                    onClick={() => stopMutation.mutate(agent.id)}
                    disabled={!isRunning || stopMutation.isPending}
                  >
                    <Square className="h-3 w-3 mr-1" />
                    Stop
                  </Button>
                </div>

                {/* Current Task */}
                {status?.current_task_id && (
                  <div className="text-xs p-2 bg-secondary rounded">
                    <span className="text-muted-foreground">Working on: </span>
                    <span className="font-mono">{status.current_task_id.slice(0, 8)}...</span>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
