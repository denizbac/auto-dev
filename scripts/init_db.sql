-- Auto-Dev Database Initialization
-- =================================
-- Run automatically by PostgreSQL container on first start

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Repositories table
CREATE TABLE IF NOT EXISTS repos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    gitlab_url TEXT NOT NULL,
    gitlab_project_id TEXT NOT NULL,
    default_branch TEXT DEFAULT 'main',
    autonomy_mode TEXT DEFAULT 'guided' CHECK (autonomy_mode IN ('full', 'guided')),
    settings JSONB DEFAULT '{}',
    webhook_secret_hash TEXT,
    token_ssm_path TEXT,
    mr_prefix TEXT DEFAULT '[AUTO-DEV]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    active BOOLEAN DEFAULT true
);

-- Tasks table
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled')),
    priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    payload JSONB DEFAULT '{}',
    result JSONB,
    error TEXT,
    created_by TEXT,
    assigned_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3
);

-- Approval queue
CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    approval_type TEXT NOT NULL CHECK (approval_type IN ('spec', 'merge', 'issue_creation', 'deploy')),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    payload JSONB DEFAULT '{}',
    reviewer TEXT,
    review_comment TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP,
    auto_approved BOOLEAN DEFAULT false,
    auto_approve_reason TEXT
);

-- Agent status
CREATE TABLE IF NOT EXISTS agent_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_type TEXT NOT NULL,
    repo_id UUID REFERENCES repos(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'error', 'stopped')),
    current_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    last_heartbeat TIMESTAMP DEFAULT NOW(),
    session_started TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Reflections (agent learning)
CREATE TABLE IF NOT EXISTS reflections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    agent_type TEXT NOT NULL,
    reflection_type TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    tags TEXT[],
    created_at TIMESTAMP DEFAULT NOW()
);

-- Learnings (extracted insights)
CREATE TABLE IF NOT EXISTS learnings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL,
    category TEXT NOT NULL,
    insight TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.5,
    usage_count INTEGER DEFAULT 0,
    last_used TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    active BOOLEAN DEFAULT true
);

-- GitLab objects tracking
CREATE TABLE IF NOT EXISTS gitlab_objects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL CHECK (object_type IN ('epic', 'issue', 'merge_request', 'pipeline')),
    gitlab_id INTEGER NOT NULL,
    gitlab_iid INTEGER,
    title TEXT,
    state TEXT,
    labels TEXT[],
    created_by_agent TEXT,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(repo_id, object_type, gitlab_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tasks_repo_status ON tasks(repo_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_agent);
CREATE INDEX IF NOT EXISTS idx_approvals_repo_status ON approvals(repo_id, status);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_approvals_created_at ON approvals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_status_type ON agent_status(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_status_heartbeat ON agent_status(last_heartbeat DESC);
CREATE INDEX IF NOT EXISTS idx_reflections_repo_agent ON reflections(repo_id, agent_type);
CREATE INDEX IF NOT EXISTS idx_learnings_repo_agent ON learnings(repo_id, agent_type) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_gitlab_objects_repo_type ON gitlab_objects(repo_id, object_type);

-- Updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at trigger
DROP TRIGGER IF EXISTS repos_updated_at ON repos;
CREATE TRIGGER repos_updated_at BEFORE UPDATE ON repos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS gitlab_objects_updated_at ON gitlab_objects;
CREATE TRIGGER gitlab_objects_updated_at BEFORE UPDATE ON gitlab_objects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Grant permissions (for app user if different from owner)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO autodev;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO autodev;

-- Initial data (optional)
-- INSERT INTO repos (name, slug, gitlab_url, gitlab_project_id) VALUES
--     ('Example Repo', 'example-repo', 'https://gitlab.com/org/example', '12345');
