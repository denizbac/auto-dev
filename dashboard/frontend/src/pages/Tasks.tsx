import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Filter, Clock, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { getTasks, getAgentConfig, getRepos, createTask, type Task } from '@/lib/api'
import { formatDate } from '@/lib/utils'

const statusConfig: Record<string, { label: string; variant: 'success' | 'warning' | 'destructive' | 'secondary'; icon: typeof Clock }> = {
  pending: { label: 'Pending', variant: 'warning', icon: Clock },
  claimed: { label: 'In Progress', variant: 'secondary', icon: Loader2 },
  completed: { label: 'Completed', variant: 'success', icon: CheckCircle },
  failed: { label: 'Failed', variant: 'destructive', icon: XCircle },
  cancelled: { label: 'Cancelled', variant: 'secondary', icon: XCircle },
}

export default function Tasks() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

  // Create task form
  const [taskDescription, setTaskDescription] = useState('')
  const [taskAgent, setTaskAgent] = useState('')
  const [taskRepo, setTaskRepo] = useState('')
  const [taskPriority, setTaskPriority] = useState('8')

  const { data: tasks } = useQuery({
    queryKey: ['tasks', statusFilter],
    queryFn: () => getTasks(statusFilter === 'all' ? undefined : statusFilter),
  })
  const { data: agentConfig } = useQuery({ queryKey: ['agent-config'], queryFn: getAgentConfig })
  const { data: repos } = useQuery({ queryKey: ['repos'], queryFn: getRepos })

  const createTaskMutation = useMutation({
    mutationFn: createTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      setCreateDialogOpen(false)
      resetForm()
    },
  })

  const resetForm = () => {
    setTaskDescription('')
    setTaskAgent('')
    setTaskRepo('')
    setTaskPriority('8')
  }

  const handleCreateTask = () => {
    if (!taskDescription.trim() || !taskAgent) return
    createTaskMutation.mutate({
      type: 'directive',
      to: taskAgent,
      priority: parseInt(taskPriority),
      repo_id: taskRepo || null,
      payload: {
        instruction: taskDescription,
        from: 'human',
        urgent: parseInt(taskPriority) >= 9,
        repo_id: taskRepo || null,
      },
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Tasks</h2>
          <p className="text-sm text-muted-foreground">
            View and manage all tasks in the queue
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[150px]">
              <Filter className="h-4 w-4 mr-2" />
              <SelectValue placeholder="Filter" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Tasks</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="claimed">In Progress</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
          <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4 mr-2" />
                Create Task
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Task</DialogTitle>
                <DialogDescription>
                  Assign a new task to an agent.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-4">
                <div>
                  <label className="text-sm font-medium">Description</label>
                  <textarea
                    className="w-full h-24 p-3 text-sm bg-background border border-input rounded-md resize-none focus:outline-none focus:ring-2 focus:ring-ring mt-1"
                    placeholder="Describe the task..."
                    value={taskDescription}
                    onChange={(e) => setTaskDescription(e.target.value)}
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium">Agent</label>
                    <Select value={taskAgent} onValueChange={setTaskAgent}>
                      <SelectTrigger className="mt-1">
                        <SelectValue placeholder="Select agent" />
                      </SelectTrigger>
                      <SelectContent>
                        {agentConfig?.agents?.map((agent) => (
                          <SelectItem key={agent.id} value={agent.id}>
                            {agent.icon} {agent.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label className="text-sm font-medium">Priority</label>
                    <Select value={taskPriority} onValueChange={setTaskPriority}>
                      <SelectTrigger className="mt-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="10">Critical (10)</SelectItem>
                        <SelectItem value="9">High (9)</SelectItem>
                        <SelectItem value="8">Normal (8)</SelectItem>
                        <SelectItem value="5">Low (5)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium">Repository (Optional)</label>
                  <Select value={taskRepo} onValueChange={setTaskRepo}>
                    <SelectTrigger className="mt-1">
                      <SelectValue placeholder="Select repository" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">Global / All Repos</SelectItem>
                      {repos?.repos?.map((repo) => (
                        <SelectItem key={repo.id} value={repo.id}>
                          {repo.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleCreateTask}
                  disabled={!taskDescription.trim() || !taskAgent || createTaskMutation.isPending}
                >
                  Create Task
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-4">
        {Object.entries(tasks?.stats ?? {}).map(([status, count]) => {
          const config = statusConfig[status]
          if (!config) return null
          return (
            <Card key={status}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{config.label}</p>
                    <p className="text-2xl font-bold">{count}</p>
                  </div>
                  <config.icon className="h-8 w-8 text-muted-foreground" />
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* Task List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tasks</CardTitle>
        </CardHeader>
        <CardContent>
          {tasks?.tasks?.length === 0 ? (
            <div className="text-center py-8">
              <Clock className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground">No tasks found</p>
            </div>
          ) : (
            <div className="space-y-3">
              {tasks?.tasks?.map((task: Task) => {
                const config = statusConfig[task.status] || statusConfig.pending
                const StatusIcon = config.icon
                return (
                  <div
                    key={task.id}
                    className="flex items-start gap-4 p-4 rounded-lg border border-border"
                  >
                    <StatusIcon className={`h-5 w-5 mt-0.5 ${
                      task.status === 'completed' ? 'text-green-500' :
                      task.status === 'failed' ? 'text-red-500' :
                      task.status === 'claimed' ? 'text-blue-500 animate-spin' :
                      'text-muted-foreground'
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium">{task.type}</span>
                        <Badge variant={config.variant}>{config.label}</Badge>
                        <Badge variant="outline">P{task.priority}</Badge>
                        {task.parent_task_id && (
                          <Badge variant="outline">Parent {task.parent_task_id.slice(0, 8)}</Badge>
                        )}
                        {task.assigned_to && (
                          <Badge variant="secondary">{task.assigned_to}</Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground line-clamp-2">
                        {typeof task.payload === 'object' && task.payload !== null
                          ? (task.payload as { instruction?: string }).instruction || JSON.stringify(task.payload)
                          : String(task.payload)}
                      </p>
                      {!!task.result && (task.status === 'completed' || task.status === 'failed') && (
                        (() => {
                          const result = task.result as { summary?: string }
                          if (!result?.summary) return null
                          return (
                            <div className="mt-2 rounded-md border border-border bg-muted/30 p-2">
                              <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Summary</p>
                              <p className="text-xs whitespace-pre-wrap">{result.summary}</p>
                            </div>
                          )
                        })()
                      )}
                      {!!task.result && (task.status === 'completed' || task.status === 'failed') && (
                        (() => {
                          const result = task.result as { output_excerpt?: string }
                          if (!result?.output_excerpt) return null
                          return (
                            <div className="mt-2 rounded-md border border-border bg-muted/40 p-2">
                              <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Output</p>
                              <pre className="text-xs whitespace-pre-wrap max-h-40 overflow-auto">
                                {result.output_excerpt}
                              </pre>
                            </div>
                          )
                        })()
                      )}
                      {!!task.result && (task.status === 'completed' || task.status === 'failed') && (
                        (() => {
                          const result = task.result as { output_url?: string; output_path?: string }
                          if (!result?.output_url && !result?.output_path) return null
                          return (
                            <div className="mt-2 rounded-md border border-border bg-muted/40 p-2">
                              <p className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">Full Output</p>
                              {result.output_url && (
                                <pre className="text-xs whitespace-pre-wrap break-all">{result.output_url}</pre>
                              )}
                              {result.output_path && !result.output_url && (
                                <pre className="text-xs whitespace-pre-wrap break-all">{result.output_path}</pre>
                              )}
                            </div>
                          )
                        })()
                      )}
                      <p className="text-xs text-muted-foreground mt-1">
                        {formatDate(task.created_at)} · ID: {task.id.slice(0, 8)}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
