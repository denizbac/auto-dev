import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Settings as SettingsIcon, Server, Database, Shield, Zap } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { getHealth, getAgentProviders, getAutonomyConfig, updateAutonomyConfig } from '@/lib/api'

export default function Settings() {
  const queryClient = useQueryClient()
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth })
  const { data: providers } = useQuery({ queryKey: ['agent-providers'], queryFn: getAgentProviders })
  const { data: autonomy } = useQuery({ queryKey: ['autonomy-config'], queryFn: getAutonomyConfig })

  const updateMutation = useMutation({
    mutationFn: updateAutonomyConfig,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['autonomy-config'] }),
  })

  const handleModeChange = (mode: 'full' | 'guided') => {
    updateMutation.mutate({ default_mode: mode })
  }

  const handleGateToggle = (gate: string, enabled: boolean) => {
    const currentGates = autonomy?.approval_gates ?? {
      issue_creation: true,
      spec_approval: true,
      merge_approval: true,
      deploy_approval: true,
    }
    updateMutation.mutate({
      approval_gates: {
        ...currentGates,
        [gate]: enabled,
      },
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold">Settings</h2>
        <p className="text-sm text-muted-foreground">
          System configuration and autonomy settings
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Autonomy Mode */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Shield className="h-4 w-4" />
              Autonomy Mode
            </CardTitle>
            <CardDescription>Control how much human oversight is required</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm">Current Mode</span>
              <Select
                value={autonomy?.default_mode ?? 'guided'}
                onValueChange={(v) => handleModeChange(v as 'full' | 'guided')}
              >
                <SelectTrigger className="w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="guided">Guided</SelectItem>
                  <SelectItem value="full">Full Autonomy</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <p className="text-xs text-muted-foreground">
              {autonomy?.default_mode === 'full'
                ? 'Agents operate autonomously within safety limits'
                : 'Human approval required for configured gates'}
            </p>
          </CardContent>
        </Card>

        {/* Approval Gates */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <SettingsIcon className="h-4 w-4" />
              Approval Gates
            </CardTitle>
            <CardDescription>Toggle which actions require human approval</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {[
              { key: 'issue_creation', label: 'Issue Creation', desc: 'Creating GitLab issues' },
              { key: 'spec_approval', label: 'Spec Approval', desc: 'Before implementation starts' },
              { key: 'merge_approval', label: 'Merge Approval', desc: 'Before merging MRs' },
              { key: 'deploy_approval', label: 'Deploy Approval', desc: 'Before deployments' },
            ].map((gate) => (
              <div key={gate.key} className="flex items-center justify-between py-2">
                <div>
                  <p className="text-sm font-medium">{gate.label}</p>
                  <p className="text-xs text-muted-foreground">{gate.desc}</p>
                </div>
                <Button
                  size="sm"
                  variant={autonomy?.approval_gates?.[gate.key as keyof typeof autonomy.approval_gates] ? 'default' : 'outline'}
                  onClick={() =>
                    handleGateToggle(
                      gate.key,
                      !autonomy?.approval_gates?.[gate.key as keyof typeof autonomy.approval_gates]
                    )
                  }
                  disabled={updateMutation.isPending}
                >
                  {autonomy?.approval_gates?.[gate.key as keyof typeof autonomy.approval_gates]
                    ? 'Required'
                    : 'Auto'}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* System Status */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Server className="h-4 w-4" />
              System Status
            </CardTitle>
            <CardDescription>Current system health and version</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm">Status</span>
              <Badge variant={health?.status === 'healthy' ? 'success' : 'destructive'}>
                {health?.status ?? 'Unknown'}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Service</span>
              <span className="text-sm text-muted-foreground">{health?.service ?? 'dashboard'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Version</span>
              <span className="text-sm text-muted-foreground">{health?.version ?? '2.0.0'}</span>
            </div>
          </CardContent>
        </Card>

        {/* LLM Configuration */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Zap className="h-4 w-4" />
              LLM Configuration
            </CardTitle>
            <CardDescription>Default provider and fallback settings</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm">Default Provider</span>
              <Badge>{providers?.default_provider ?? 'codex'}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Fallback</span>
              <Badge variant="outline">Auto (on rate limit)</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Agents Configured</span>
              <span className="text-sm text-muted-foreground">
                {providers?.providers?.length ?? 0}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Database */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Database className="h-4 w-4" />
              Database
            </CardTitle>
            <CardDescription>PostgreSQL connection status</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm">Type</span>
              <span className="text-sm text-muted-foreground">PostgreSQL</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Status</span>
              <Badge variant="success">Connected</Badge>
            </div>
          </CardContent>
        </Card>

        {/* Safety Limits */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Shield className="h-4 w-4" />
              Safety Limits
            </CardTitle>
            <CardDescription>Daily limits even in full autonomy</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm">Max Issues/Day</span>
              <span className="text-sm text-muted-foreground">
                {autonomy?.safety_limits?.max_issues_per_day ?? 10}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Max MRs/Day</span>
              <span className="text-sm text-muted-foreground">
                {autonomy?.safety_limits?.max_mrs_per_day ?? 20}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Max Deploys/Day</span>
              <span className="text-sm text-muted-foreground">
                {autonomy?.safety_limits?.max_deployments_per_day ?? 5}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Human for Breaking Changes</span>
              <Badge variant={autonomy?.safety_limits?.require_human_for_breaking_changes ? 'default' : 'outline'}>
                {autonomy?.safety_limits?.require_human_for_breaking_changes ? 'Yes' : 'No'}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
