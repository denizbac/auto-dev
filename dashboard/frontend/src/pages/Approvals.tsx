import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Clock, GitMerge, Rocket, FileText, AlertCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  getPendingApprovals,
  approvePendingItem,
  rejectPendingItem,
  type PendingApproval,
} from '@/lib/api'
import { formatDate } from '@/lib/utils'
import { useState } from 'react'

const typeConfig: Record<string, { label: string; icon: typeof Clock; color: string }> = {
  task: { label: 'Task', icon: Clock, color: 'text-blue-400' },
  issue: { label: 'Issue', icon: FileText, color: 'text-purple-400' },
  issue_creation: { label: 'Issue', icon: FileText, color: 'text-purple-400' },
  spec: { label: 'Spec', icon: FileText, color: 'text-cyan-400' },
  specification: { label: 'Spec', icon: FileText, color: 'text-cyan-400' },
  merge: { label: 'Merge', icon: GitMerge, color: 'text-orange-400' },
  mr: { label: 'Merge', icon: GitMerge, color: 'text-orange-400' },
  merge_request: { label: 'Merge', icon: GitMerge, color: 'text-orange-400' },
  deploy: { label: 'Deploy', icon: Rocket, color: 'text-green-400' },
  deployment: { label: 'Deploy', icon: Rocket, color: 'text-green-400' },
}

export default function Approvals() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<string>('all')

  const { data: pendingData } = useQuery({
    queryKey: ['pending-approvals'],
    queryFn: getPendingApprovals,
    refetchInterval: 5000,
  })

  const approveMutation = useMutation({
    mutationFn: (id: string) => approvePendingItem(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pending-approvals'] }),
  })

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => rejectPendingItem(id, reason),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['pending-approvals'] }),
  })

  const stats = pendingData?.stats ?? { tasks: 0, merges: 0, deploys: 0, specs: 0, issues: 0, total: 0 }

  const filteredApprovals = pendingData?.approvals?.filter((approval) => {
    if (filter === 'all') return true
    const approvalType = approval.approval_type || approval.item_type
    if (filter === 'tasks') return approvalType === 'task' || approval.item_type === 'task'
    if (filter === 'merges') return ['merge', 'mr', 'merge_request'].includes(approvalType || '')
    if (filter === 'deploys') return ['deploy', 'deployment'].includes(approvalType || '')
    if (filter === 'specs') return ['spec', 'specification'].includes(approvalType || '')
    return true
  }) ?? []

  const getApprovalTitle = (approval: PendingApproval): string => {
    if (approval.title) return approval.title
    if (approval.payload?.instruction) return String(approval.payload.instruction)
    if (approval.type) return `${approval.type} task`
    return 'Pending approval'
  }

  const getApprovalDescription = (approval: PendingApproval): string => {
    if (approval.description) return approval.description
    if (approval.payload?.from) return `From: ${approval.payload.from}`
    if (approval.created_by) return `Created by: ${approval.created_by}`
    return ''
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold">Approvals</h2>
        <p className="text-sm text-muted-foreground">
          Review and approve pending items ({stats.total} pending)
        </p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card
          className={`cursor-pointer transition-colors ${filter === 'all' ? 'border-primary' : ''}`}
          onClick={() => setFilter('all')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Pending</p>
                <p className="text-2xl font-bold text-orange-400">{stats.total}</p>
              </div>
              <Clock className="h-8 w-8 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors ${filter === 'tasks' ? 'border-primary' : ''}`}
          onClick={() => setFilter('tasks')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Tasks</p>
                <p className="text-2xl font-bold text-blue-400">{stats.tasks}</p>
              </div>
              <AlertCircle className="h-8 w-8 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors ${filter === 'specs' ? 'border-primary' : ''}`}
          onClick={() => setFilter('specs')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Specs</p>
                <p className="text-2xl font-bold text-cyan-400">{stats.specs}</p>
              </div>
              <FileText className="h-8 w-8 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors ${filter === 'merges' ? 'border-primary' : ''}`}
          onClick={() => setFilter('merges')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Merges</p>
                <p className="text-2xl font-bold text-orange-400">{stats.merges}</p>
              </div>
              <GitMerge className="h-8 w-8 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors ${filter === 'deploys' ? 'border-primary' : ''}`}
          onClick={() => setFilter('deploys')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Deploys</p>
                <p className="text-2xl font-bold text-green-400">{stats.deploys}</p>
              </div>
              <Rocket className="h-8 w-8 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Pending Approvals List */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pending Approvals</CardTitle>
        </CardHeader>
        <CardContent>
          {filteredApprovals.length === 0 ? (
            <div className="text-center py-8">
              <CheckCircle className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
              <p className="text-muted-foreground">No pending approvals</p>
              <p className="text-sm text-muted-foreground mt-1">
                Items requiring human approval will appear here
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {filteredApprovals.map((approval: PendingApproval) => {
                const approvalType = approval.approval_type || approval.item_type || 'task'
                const config = typeConfig[approvalType] || typeConfig.task
                const TypeIcon = config.icon

                return (
                  <div key={approval.id} className="p-4 rounded-lg border border-border">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-start gap-3">
                        <TypeIcon className={`h-5 w-5 mt-0.5 ${config.color}`} />
                        <div>
                          <h3 className="font-semibold">{getApprovalTitle(approval)}</h3>
                          <p className="text-sm text-muted-foreground mt-1">
                            {getApprovalDescription(approval)}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="warning">{config.label}</Badge>
                        {approval.priority && (
                          <Badge variant="outline">P{approval.priority}</Badge>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-4 text-sm mb-4">
                      {approval.repo_id && (
                        <div>
                          <p className="text-muted-foreground">Repository</p>
                          <p className="font-medium">{approval.repo_id}</p>
                        </div>
                      )}
                      {approval.assigned_to && (
                        <div>
                          <p className="text-muted-foreground">Assigned To</p>
                          <p className="font-medium">{approval.assigned_to}</p>
                        </div>
                      )}
                      {approval.gitlab_ref && (
                        <div>
                          <p className="text-muted-foreground">GitLab Ref</p>
                          <p className="font-medium font-mono text-xs">{approval.gitlab_ref}</p>
                        </div>
                      )}
                      <div>
                        <p className="text-muted-foreground">Submitted</p>
                        <p className="font-medium">{formatDate(approval.created_at)}</p>
                      </div>
                    </div>

                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => approveMutation.mutate(approval.id)}
                        disabled={approveMutation.isPending}
                      >
                        <CheckCircle className="h-4 w-4 mr-1" />
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => rejectMutation.mutate({ id: approval.id, reason: 'Rejected by human reviewer' })}
                        disabled={rejectMutation.isPending}
                      >
                        <XCircle className="h-4 w-4 mr-1" />
                        Reject
                      </Button>
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
