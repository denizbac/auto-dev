import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, GitBranch, Send, ExternalLink, Github } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import {
  getRepos,
  getAgentConfig,
  createRepo,
  createTask,
  type Repo,
} from '@/lib/api'
import { formatDate } from '@/lib/utils'

export default function Repositories() {
  const queryClient = useQueryClient()
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [selectedRepo, setSelectedRepo] = useState<Repo | null>(null)
  const [instruction, setInstruction] = useState('')
  const [instructionAgent, setInstructionAgent] = useState('pm')
  const [instructionPriority, setInstructionPriority] = useState('8')

  // Form state for adding repo
  const [newRepoName, setNewRepoName] = useState('')
  const [newRepoProvider, setNewRepoProvider] = useState<'gitlab' | 'github'>('github')
  const [newRepoUrl, setNewRepoUrl] = useState('https://github.com')
  const [newRepoProjectId, setNewRepoProjectId] = useState('')
  const [newRepoAutonomy, setNewRepoAutonomy] = useState<'guided' | 'full'>('guided')

  const { data: repos } = useQuery({ queryKey: ['repos'], queryFn: getRepos })
  const { data: agentConfig } = useQuery({ queryKey: ['agent-config'], queryFn: getAgentConfig })

  const createRepoMutation = useMutation({
    mutationFn: createRepo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['repos'] })
      setAddDialogOpen(false)
      resetForm()
    },
  })

  const createTaskMutation = useMutation({
    mutationFn: createTask,
    onSuccess: () => {
      setInstruction('')
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  const resetForm = () => {
    setNewRepoName('')
    setNewRepoProvider('github')
    setNewRepoUrl('https://github.com')
    setNewRepoProjectId('')
    setNewRepoAutonomy('guided')
  }

  const handleProviderChange = (provider: 'gitlab' | 'github') => {
    setNewRepoProvider(provider)
    setNewRepoUrl(provider === 'github' ? 'https://github.com' : 'https://gitlab.nimbus.amgen.com')
  }

  const handleAddRepo = () => {
    createRepoMutation.mutate({
      name: newRepoName,
      provider: newRepoProvider,
      gitlab_url: newRepoUrl,
      gitlab_project_id: newRepoProjectId,
      autonomy_mode: newRepoAutonomy,
    })
  }

  const handleSendInstruction = () => {
    if (!instruction.trim() || !selectedRepo) return
    createTaskMutation.mutate({
      type: 'directive',
      to: instructionAgent,
      priority: parseInt(instructionPriority),
      repo_id: selectedRepo.id,
      payload: {
        instruction: instruction,
        from: 'human',
        urgent: parseInt(instructionPriority) >= 9,
        repo_id: selectedRepo.id,
      },
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Repositories</h2>
          <p className="text-sm text-muted-foreground">
            Manage GitHub and GitLab repositories and send targeted instructions
          </p>
        </div>
        <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              Add Repository
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add Repository</DialogTitle>
              <DialogDescription>
                Connect a GitHub or GitLab repository for Auto-Dev to work on.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div>
                <label className="text-sm font-medium">Provider</label>
                <Select value={newRepoProvider} onValueChange={(v) => handleProviderChange(v as 'gitlab' | 'github')}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="github">GitHub</SelectItem>
                    <SelectItem value="gitlab">GitLab</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-sm font-medium">Name</label>
                <Input
                  placeholder="My Project"
                  value={newRepoName}
                  onChange={(e) => setNewRepoName(e.target.value)}
                />
              </div>
              <div>
                <label className="text-sm font-medium">
                  {newRepoProvider === 'github' ? 'Owner/Repo' : 'Project ID or Path'}
                </label>
                <Input
                  placeholder={newRepoProvider === 'github' ? 'owner/repo' : 'group/project or 12345'}
                  value={newRepoProjectId}
                  onChange={(e) => setNewRepoProjectId(e.target.value)}
                />
              </div>
              <div>
                <label className="text-sm font-medium">Autonomy Mode</label>
                <Select value={newRepoAutonomy} onValueChange={(v) => setNewRepoAutonomy(v as 'guided' | 'full')}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="guided">Guided (requires approvals)</SelectItem>
                    <SelectItem value="full">Full Autonomy</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
                Cancel
              </Button>
              <Button onClick={handleAddRepo} disabled={createRepoMutation.isPending}>
                Add Repository
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Repository List */}
        <div className="lg:col-span-2 space-y-4">
          {repos?.repos?.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center">
                <GitBranch className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <p className="text-muted-foreground">No repositories configured yet.</p>
                <Button className="mt-4" onClick={() => setAddDialogOpen(true)}>
                  <Plus className="h-4 w-4 mr-2" />
                  Add Your First Repository
                </Button>
              </CardContent>
            </Card>
          ) : (
            repos?.repos?.map((repo) => (
              <Card
                key={repo.id}
                className={`cursor-pointer transition-colors ${
                  selectedRepo?.id === repo.id ? 'border-primary' : 'hover:border-primary/50'
                }`}
                onClick={() => setSelectedRepo(repo)}
              >
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      {repo.provider === 'github' ? (
                        <Github className="h-5 w-5 text-muted-foreground" />
                      ) : (
                        <GitBranch className="h-5 w-5 text-muted-foreground" />
                      )}
                      <div>
                        <h3 className="font-medium">{repo.name}</h3>
                        <p className="text-sm text-muted-foreground">
                          {repo.provider === 'github'
                            ? `github.com/${repo.gitlab_project_id}`
                            : repo.gitlab_url}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="capitalize">
                        {repo.provider || 'gitlab'}
                      </Badge>
                      <Badge variant={repo.autonomy_mode === 'full' ? 'success' : 'secondary'}>
                        {repo.autonomy_mode}
                      </Badge>
                      <Badge variant={repo.active ? 'success' : 'destructive'}>
                        {repo.active ? 'Active' : 'Inactive'}
                      </Badge>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-muted-foreground">
                    <span>Branch: {repo.default_branch}</span>
                    <span>Added: {formatDate(repo.created_at)}</span>
                    <a
                      href={repo.provider === 'github'
                        ? `https://github.com/${repo.gitlab_project_id}`
                        : `${repo.gitlab_url}/${repo.gitlab_project_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 hover:text-foreground"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <ExternalLink className="h-3 w-3" />
                      Open in {repo.provider === 'github' ? 'GitHub' : 'GitLab'}
                    </a>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>

        {/* Instruction Panel */}
        <div>
          <Card className="sticky top-6">
            <CardHeader>
              <CardTitle className="text-base">Send Instruction</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {selectedRepo ? (
                <>
                  <div className="p-3 bg-secondary rounded-lg">
                    <p className="text-xs text-muted-foreground">Target Repository</p>
                    <p className="font-medium">{selectedRepo.name}</p>
                  </div>

                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">Instruction</label>
                    <textarea
                      className="w-full h-24 p-3 text-sm bg-background border border-input rounded-md resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                      placeholder="e.g., Create an issue for implementing user authentication..."
                      value={instruction}
                      onChange={(e) => setInstruction(e.target.value)}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-muted-foreground mb-1 block">Agent</label>
                      <Select value={instructionAgent} onValueChange={setInstructionAgent}>
                        <SelectTrigger className="h-9">
                          <SelectValue />
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
                      <label className="text-xs text-muted-foreground mb-1 block">Priority</label>
                      <Select value={instructionPriority} onValueChange={setInstructionPriority}>
                        <SelectTrigger className="h-9">
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

                  <Button
                    className="w-full"
                    onClick={handleSendInstruction}
                    disabled={!instruction.trim() || createTaskMutation.isPending}
                  >
                    <Send className="h-4 w-4 mr-2" />
                    Send Instruction
                  </Button>

                  {/* Quick Actions */}
                  <div className="space-y-2">
                    <p className="text-xs text-muted-foreground">Quick Actions</p>
                    <div className="flex flex-wrap gap-2">
                      {[
                        { label: 'Create Issue', text: 'Create an issue to track: ' },
                        { label: 'Implement Feature', text: 'Implement a feature for: ' },
                        { label: 'Fix Bug', text: 'Fix the bug where: ' },
                        { label: 'Review Code', text: 'Review the latest changes in: ' },
                        { label: 'Run Tests', text: 'Run the test suite and report results' },
                      ].map((action) => (
                        <Button
                          key={action.label}
                          variant="outline"
                          size="sm"
                          className="text-xs"
                          onClick={() => setInstruction(action.text)}
                        >
                          {action.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-center py-8">
                  <GitBranch className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                  <p className="text-sm text-muted-foreground">
                    Select a repository to send instructions
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
