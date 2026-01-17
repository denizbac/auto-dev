import { useQuery } from '@tanstack/react-query'
import {
  Brain,
  TrendingUp,
  Clock,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Activity,
  Lightbulb,
  MessageSquare,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { getOutcomes, getOutcomeStats, getReflections, getLearnings } from '@/lib/api'
import { formatDate, cn } from '@/lib/utils'

export default function Learnings() {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['outcome-stats'],
    queryFn: () => getOutcomeStats(30),
  })

  const { data: outcomes, isLoading: outcomesLoading } = useQuery({
    queryKey: ['outcomes'],
    queryFn: () => getOutcomes(50),
  })

  const { data: reflections } = useQuery({
    queryKey: ['reflections'],
    queryFn: () => getReflections(30),
  })

  const { data: learnings } = useQuery({
    queryKey: ['learnings'],
    queryFn: () => getLearnings(false, 30),
  })

  // Calculate aggregate stats
  const totalTasks = stats?.by_agent?.reduce((sum, a) => sum + a.total, 0) ?? 0
  const totalSuccess = stats?.by_agent?.reduce((sum, a) => sum + a.success, 0) ?? 0
  const overallSuccessRate = totalTasks > 0 ? (totalSuccess / totalTasks) * 100 : 0

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return '-'
    if (seconds < 60) return `${Math.round(seconds)}s`
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`
    return `${(seconds / 3600).toFixed(1)}h`
  }

  const getOutcomeBadge = (outcome: string) => {
    switch (outcome) {
      case 'success':
        return <Badge variant="success">Success</Badge>
      case 'failure':
        return <Badge variant="destructive">Failed</Badge>
      case 'partial':
        return <Badge variant="secondary">Partial</Badge>
      default:
        return <Badge variant="outline">{outcome}</Badge>
    }
  }

  const ProgressBar = ({ rate, className }: { rate: number; className?: string }) => (
    <div className={cn('h-2 rounded-full bg-secondary overflow-hidden', className)}>
      <div
        className={cn(
          'h-full rounded-full transition-all',
          rate >= 80 ? 'bg-green-500' : rate >= 50 ? 'bg-yellow-500' : 'bg-red-500'
        )}
        style={{ width: `${rate}%` }}
      />
    </div>
  )

  if (statsLoading && outcomesLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-pulse text-muted-foreground">Loading learnings...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Brain className="h-6 w-6" />
          Agent Learnings
        </h1>
        <p className="text-muted-foreground">
          Performance metrics and task outcomes from the last {stats?.period_days ?? 30} days
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Tasks</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-400">{totalTasks}</div>
            <p className="text-xs text-muted-foreground">Completed outcomes</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className={cn(
              'text-2xl font-bold',
              overallSuccessRate >= 80 ? 'text-green-400' :
              overallSuccessRate >= 50 ? 'text-yellow-400' : 'text-red-400'
            )}>
              {overallSuccessRate.toFixed(1)}%
            </div>
            <p className="text-xs text-muted-foreground">Overall performance</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Agents</CardTitle>
            <CheckCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-purple-400">
              {stats?.by_agent?.length ?? 0}
            </div>
            <p className="text-xs text-muted-foreground">With recorded outcomes</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Recent Failures</CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-orange-400">
              {stats?.recent_failures?.length ?? 0}
            </div>
            <p className="text-xs text-muted-foreground">Requires attention</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Performance by Agent */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Performance by Agent
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!stats?.by_agent?.length ? (
              <p className="text-sm text-muted-foreground">No agent data yet</p>
            ) : (
              <div className="space-y-4">
                {stats.by_agent.map((agent) => (
                  <div key={agent.agent_id} className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium capitalize">{agent.agent_id}</span>
                      <span className="text-muted-foreground">
                        {agent.success}/{agent.total} ({(agent.rate * 100).toFixed(0)}%)
                      </span>
                    </div>
                    <ProgressBar rate={agent.rate * 100} />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Performance by Task Type */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="h-4 w-4" />
              Performance by Task Type
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!stats?.by_task_type?.length ? (
              <p className="text-sm text-muted-foreground">No task type data yet</p>
            ) : (
              <div className="space-y-4">
                {stats.by_task_type.slice(0, 8).map((taskType) => (
                  <div key={taskType.task_type} className="space-y-2">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{taskType.task_type.replace(/_/g, ' ')}</span>
                      <span className="text-muted-foreground">
                        {taskType.success}/{taskType.total} ({(taskType.rate * 100).toFixed(0)}%)
                      </span>
                    </div>
                    <ProgressBar rate={taskType.rate * 100} />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent Failures */}
      {stats?.recent_failures && stats.recent_failures.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2 text-orange-400">
              <XCircle className="h-4 w-4" />
              Recent Failures
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats.recent_failures.map((failure, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-3 rounded-lg border border-orange-500/30 bg-orange-500/5 p-3"
                >
                  <AlertTriangle className="h-4 w-4 text-orange-500 mt-0.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant="outline" className="capitalize">
                        {failure.agent_id}
                      </Badge>
                      <span className="text-sm text-muted-foreground">
                        {failure.task_type.replace(/_/g, ' ')}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {formatDate(failure.created_at)}
                      </span>
                    </div>
                    {failure.error_summary && (
                      <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                        {failure.error_summary}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Outcomes Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Recent Outcomes
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!outcomes?.outcomes?.length ? (
            <p className="text-sm text-muted-foreground">No outcomes recorded yet</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left font-medium p-2">Agent</th>
                    <th className="text-left font-medium p-2">Task Type</th>
                    <th className="text-left font-medium p-2">Outcome</th>
                    <th className="text-left font-medium p-2">Duration</th>
                    <th className="text-left font-medium p-2">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {outcomes.outcomes.slice(0, 20).map((outcome) => (
                    <tr key={outcome.id} className="border-b border-border/50 hover:bg-accent/50">
                      <td className="p-2 capitalize">{outcome.agent_id}</td>
                      <td className="p-2">{outcome.task_type.replace(/_/g, ' ')}</td>
                      <td className="p-2">{getOutcomeBadge(outcome.outcome)}</td>
                      <td className="p-2 text-muted-foreground">
                        {formatDuration(outcome.duration_seconds)}
                      </td>
                      <td className="p-2 text-muted-foreground">{formatDate(outcome.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Validated Learnings */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Lightbulb className="h-4 w-4" />
            Validated Learnings
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!learnings?.learnings?.length ? (
            <p className="text-sm text-muted-foreground">No learnings recorded yet</p>
          ) : (
            <div className="space-y-3">
              {learnings.learnings.slice(0, 10).map((learning) => (
                <div key={learning.id} className="flex items-start gap-3 p-3 rounded-lg border">
                  <Badge variant="outline" className="capitalize shrink-0">
                    {learning.agent_id}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm">{learning.content}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="secondary" className="text-xs">
                        {learning.category}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        validated {learning.validation_count}x
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Reflections */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <MessageSquare className="h-4 w-4" />
            Recent Reflections
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!reflections?.reflections?.length ? (
            <p className="text-sm text-muted-foreground">No reflections yet</p>
          ) : (
            <div className="space-y-3 max-h-[400px] overflow-y-auto">
              {reflections.reflections.slice(0, 15).map((r) => (
                <div key={r.id} className="border-b border-border pb-3 last:border-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant={r.reflection_type === 'TASK_COMPLETION' ? 'default' : 'destructive'}>
                      {r.reflection_type.replace(/_/g, ' ')}
                    </Badge>
                    <span className="text-sm font-medium capitalize">{r.agent_id}</span>
                    <span className="text-xs text-muted-foreground">{formatDate(r.created_at)}</span>
                  </div>
                  <p className="text-sm mt-1">{r.summary}</p>
                  {r.confidence !== undefined && (
                    <span className="text-xs text-muted-foreground">
                      Confidence: {(r.confidence * 10).toFixed(0)}/10
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
