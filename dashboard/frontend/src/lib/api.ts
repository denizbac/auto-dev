const API_BASE = '/api'

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }

  return response.json()
}

// Stats & Status
export const getStats = () => fetchAPI<StatsResponse>('/stats')
export const getStatus = () => fetchAPI<StatusResponse>('/status')
export const getHealth = () => fetchAPI<HealthResponse>('/health')

// Agents
export const getAgentConfig = () => fetchAPI<AgentConfigResponse>('/agent-config')
export const getAgentStatuses = () => fetchAPI<AgentStatusesResponse>('/agent-statuses')
export const getAgentProviders = () => fetchAPI<AgentProvidersResponse>('/agent-providers')
export const startAgent = (agentType: string) =>
  fetchAPI<ActionResponse>(`/agent/start/${agentType}`, { method: 'POST' })
export const stopAgent = (agentType: string) =>
  fetchAPI<ActionResponse>(`/agent/stop/${agentType}`, { method: 'POST' })
export const startAllAgents = () =>
  fetchAPI<ActionResponse>('/agent/start', { method: 'POST' })
export const stopAllAgents = () =>
  fetchAPI<ActionResponse>('/agent/stop', { method: 'POST' })
export const setAgentProvider = (agentType: string, provider: string) =>
  fetchAPI<ActionResponse>(`/agent/provider/${agentType}`, {
    method: 'POST',
    body: JSON.stringify({ provider }),
  })

// Repositories
export const getRepos = () => fetchAPI<ReposResponse>('/repos')
export const createRepo = (data: CreateRepoRequest) =>
  fetchAPI<ActionResponse>('/repos', {
    method: 'POST',
    body: JSON.stringify(data),
  })
export const updateRepo = (repoId: string, data: Partial<UpdateRepoRequest>) =>
  fetchAPI<ActionResponse>(`/repos/${repoId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })

// Tasks
export const getTasks = (status?: string) =>
  fetchAPI<TasksResponse>(`/tasks${status ? `?status=${status}` : ''}`)
export const getAgentTasks = (agent?: string, status?: string) => {
  const params = new URLSearchParams()
  if (agent) params.append('agent', agent)
  if (status) params.append('status', status)
  return fetchAPI<AgentTasksResponse>(`/agent-tasks?${params}`)
}
export const createTask = (data: CreateTaskRequest) =>
  fetchAPI<CreateTaskResponse>('/tasks', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// Autonomy Config
export const getAutonomyConfig = () => fetchAPI<AutonomyConfigResponse>('/config/autonomy')
export const updateAutonomyConfig = (config: Partial<AutonomyConfig>) =>
  fetchAPI<AutonomyUpdateResponse>('/config/autonomy', {
    method: 'PUT',
    body: JSON.stringify(config),
  })

// Pending Approvals (new system)
export const getPendingApprovals = () => fetchAPI<PendingApprovalsResponse>('/pending-approvals')
export const approvePendingItem = (itemId: string, notes?: string) =>
  fetchAPI<ActionResponse>(`/pending-approvals/${itemId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  })
export const rejectPendingItem = (itemId: string, reason: string) =>
  fetchAPI<ActionResponse>(`/pending-approvals/${itemId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })

// Legacy Approvals (kept for backwards compatibility)
export const getApprovals = (status?: string) =>
  fetchAPI<ApprovalsResponse>(`/approvals${status ? `?status=${status}` : ''}`)
export const approveItem = (itemId: string, notes?: string) =>
  fetchAPI<ActionResponse>(`/approvals/${itemId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  })
export const rejectItem = (itemId: string, reason: string) =>
  fetchAPI<ActionResponse>(`/approvals/${itemId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })

// Projects
export const getProjects = (status?: string) =>
  fetchAPI<ProjectsResponse>(`/projects${status ? `?status=${status}` : ''}`)
export const approveProject = (projectId: string, notes?: string) =>
  fetchAPI<ActionResponse>(`/projects/${projectId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  })
export const rejectProject = (projectId: string, reason: string) =>
  fetchAPI<ActionResponse>(`/projects/${projectId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
export const deferProject = (projectId: string, notes?: string) =>
  fetchAPI<ActionResponse>(`/projects/${projectId}/defer`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  })

// Discussions & Chat
export const getDiscussions = () => fetchAPI<DiscussionsResponse>('/discussions')
export const getChat = () => fetchAPI<ChatResponse>('/chat')
export const sendChat = (message: string) =>
  fetchAPI<ActionResponse>('/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
export const sendDirective = (message: string, priority?: number) =>
  fetchAPI<ActionResponse>('/directive', {
    method: 'POST',
    body: JSON.stringify({ message, priority }),
  })

// Types
export interface StatsResponse {
  income: { total_30d: number; by_source: Record<string, number> }
  tokens: { total_7d: number; cost_7d: number; daily_average: number }
  efficiency: { income_per_1k_tokens: number }
}

export interface StatusResponse {
  is_running: boolean
  current_session: unknown | null
  total_sessions: number
  message: string
}

export interface HealthResponse {
  status: string
  service: string
  version: string
}

export interface Agent {
  id: string
  name: string
  description: string
  icon: string
  task_types: string[]
  model: string
  provider: string | null
}

export interface AgentConfigResponse {
  agents: Agent[]
}

export interface AgentStatus {
  agent_id: string
  status: 'online' | 'offline' | 'working' | 'idle' | 'disabled' | 'rate_limited' | 'running' | 'paused' | 'stopped' | 'starting'
  current_task_id: string | null
  tasks_completed: number
  tokens_used: number
  enabled?: boolean
  last_heartbeat?: string
  session_start?: string
}

export interface RateLimitInfo {
  limited: boolean
  provider: string
  reset_time: string
  set_by?: string
  remaining_seconds: number
}

export interface AgentStatusesResponse {
  agents: Record<string, AgentStatus>
  rate_limit?: RateLimitInfo | null
}

export interface AgentProvidersResponse {
  providers: Array<{
    agent_id: string
    provider_override: string | null
    default_provider: string
    active_provider: string | null
  }>
  default_provider: string
}

export interface Repo {
  id: string
  name: string
  slug: string
  provider: 'gitlab' | 'github'
  gitlab_url: string
  gitlab_project_id: string
  default_branch: string
  autonomy_mode: 'full' | 'guided'
  active: boolean
  created_at: string
}

export interface ReposResponse {
  repos: Repo[]
}

export interface CreateRepoRequest {
  name: string
  provider?: 'gitlab' | 'github'
  gitlab_url: string
  gitlab_project_id: string
  default_branch?: string
  autonomy_mode?: 'full' | 'guided'
}

export interface UpdateRepoRequest {
  name?: string
  default_branch?: string
  autonomy_mode?: 'full' | 'guided'
  active?: boolean
  settings?: Record<string, unknown>
}

export interface Task {
  id: string
  type: string
  priority: number
  payload: Record<string, unknown>
  status: string
  created_at: string
  assigned_to?: string
  repo_id?: string
  parent_task_id?: string
  result?: unknown
}

export interface TasksResponse {
  tasks: Task[]
  stats: Record<string, number>
}

export interface AgentTasksResponse {
  agents: Record<string, Task[]>
  summary: Record<string, { total: number; completed: number; pending: number; failed: number }>
}

export interface CreateTaskRequest {
  type: string
  to: string
  priority: number
  repo_id?: string | null
  parent_task_id?: string | null
  payload: {
    instruction: string
    from: string
    urgent?: boolean
    repo_id?: string | null
  }
}

export interface CreateTaskResponse {
  status: string
  task_id: string
  repo_id?: string | null
  assigned_to?: string | null
}

export interface Approval {
  id: string
  product_name: string
  platform: string
  files_path: string
  price: string
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
  reviewed_at?: string
  reviewer_notes?: string
}

export interface ApprovalsResponse {
  approvals: Approval[]
  pending_count: number
}

export interface Project {
  id: string
  title: string
  hunter_pitch: string
  hunter_rating: number
  market_size: string
  max_revenue_estimate: string
  critic_evaluation: string
  critic_rating: number
  cons: string
  differentiation: string
  spec_path: string
  effort_estimate: string
  status: 'pending' | 'approved' | 'rejected' | 'deferred'
  submitted_by: string
  reviewer_notes?: string
  created_at: string
  reviewed_at?: string
  combined_rating: number
}

export interface ProjectsResponse {
  projects: Project[]
  stats: { pending: number; deferred: number; approved: number; rejected: number }
}

export interface Discussion {
  id: string
  author: string
  topic: string
  content: string
  created_at: string
}

export interface DiscussionsResponse {
  discussions: Discussion[]
}

export interface ChatMessage {
  id: string
  author: string
  content: string
  created_at: string
}

export interface ChatResponse {
  messages: ChatMessage[]
}

export interface ActionResponse {
  success?: boolean
  status?: string
  message?: string
  error?: string
}

// Autonomy Config Types
export interface ApprovalGates {
  issue_creation: boolean
  spec_approval: boolean
  merge_approval: boolean
  deploy_approval: boolean
}

export interface AutoApproveThresholds {
  architect_confidence?: number
  reviewer_score?: number
  security_severity?: string
  test_coverage?: number
}

export interface SafetyLimits {
  max_issues_per_day?: number
  max_mrs_per_day?: number
  max_deployments_per_day?: number
  require_human_for_breaking_changes?: boolean
  require_human_for_security_fixes?: boolean
}

export interface AutonomyConfig {
  default_mode: 'full' | 'guided'
  approval_gates: ApprovalGates
  auto_approve_thresholds: AutoApproveThresholds
  safety_limits: SafetyLimits
}

export interface AutonomyConfigResponse extends AutonomyConfig {}

export interface AutonomyUpdateResponse {
  success: boolean
  autonomy: AutonomyConfig
}

// Pending Approvals Types
export interface PendingApproval {
  id: string
  item_type: 'task' | 'approval'
  approval_type?: string
  type?: string
  priority?: number
  payload?: Record<string, unknown>
  title?: string
  description?: string
  context?: Record<string, unknown>
  assigned_to?: string
  submitted_by?: string
  created_by?: string
  repo_id?: string
  gitlab_ref?: string
  created_at: string
}

export interface PendingApprovalsResponse {
  approvals: PendingApproval[]
  stats: {
    tasks: number
    merges: number
    deploys: number
    specs: number
    issues: number
    total: number
  }
}

// Task Outcomes (Learnings)
export interface TaskOutcome {
  id: string
  task_id: string
  repo_id: string
  agent_id: string
  task_type: string
  outcome: 'success' | 'failure' | 'partial'
  duration_seconds: number | null
  error_summary: string | null
  context_summary: string | null
  created_at: string
}

export interface OutcomeAgentStats {
  agent_id: string
  total: number
  success: number
  failure: number
  rate: number
}

export interface OutcomeTypeStats {
  task_type: string
  total: number
  success: number
  failure: number
  rate: number
}

export interface RecentFailure {
  agent_id: string
  task_type: string
  error_summary: string | null
  created_at: string
}

export interface OutcomeStats {
  by_agent: OutcomeAgentStats[]
  by_task_type: OutcomeTypeStats[]
  recent_failures: RecentFailure[]
  period_days: number
}

export interface OutcomesResponse {
  outcomes: TaskOutcome[]
}

export const getOutcomes = (limit = 50) =>
  fetchAPI<OutcomesResponse>(`/outcomes?limit=${limit}`)

export const getOutcomeStats = (days = 30) =>
  fetchAPI<OutcomeStats>(`/outcomes/stats?days=${days}`)

// ==================== Reflections ====================

export interface Reflection {
  id: string
  agent_id: string
  task_id: string | null
  reflection_type: string
  summary: string
  confidence: number
  tags: string[]
  created_at: string
}

export interface ReflectionStats {
  by_agent: Array<{ agent_id: string; count: number; avg_confidence: number }>
  by_type: Array<{ type: string; count: number }>
  period_days: number
}

export interface ReflectionsResponse {
  reflections: Reflection[]
}

export const getReflections = (limit = 50) =>
  fetchAPI<ReflectionsResponse>(`/reflections?limit=${limit}`)

export const getReflectionStats = (days = 30) =>
  fetchAPI<ReflectionStats>(`/reflections/stats?days=${days}`)

// ==================== Learnings ====================

export interface Learning {
  id: string
  agent_id: string
  category: string
  content: string
  confidence: number
  validation_count: number
  created_at: string
}

export interface LearningsResponse {
  learnings: Learning[]
}

export const getLearnings = (validatedOnly = false, limit = 50) =>
  fetchAPI<LearningsResponse>(
    `/learnings?validated_only=${validatedOnly}&limit=${limit}`
  )
