#!/bin/bash
# =============================================================================
# Multi-Agent Launcher for Autonomous Claude
# =============================================================================
#
# Starts specialized agents in tmux sessions for parallel operation.
#
# Usage:
#   ./start_agents.sh              # Start all agents
#   ./start_agents.sh pm           # Start only PM agent
#   ./start_agents.sh architect    # Start only architect
#   ./start_agents.sh builder      # Start only builder
#   ./start_agents.sh reviewer     # Start only reviewer
#   ./start_agents.sh tester       # Start only tester
#   ./start_agents.sh security     # Start only security scanner
#   ./start_agents.sh devops       # Start only devops agent
#   ./start_agents.sh bug_finder   # Start only bug finder
#   ./start_agents.sh stop         # Stop all agents
#   ./start_agents.sh status       # Check status of all agents
#
# =============================================================================

set -e

# Configuration
PROJECT_DIR="/auto-dev"
VENV_DIR="${PROJECT_DIR}/venv"
LOG_DIR="${PROJECT_DIR}/logs"
AGENT_RUNNER="${PROJECT_DIR}/watcher/agent_runner.py"

# Agent definitions matching config/settings.yaml
# pm: project management, architect: design, builder: implementation,
# reviewer: code review, tester: QA, security: security scanning,
# devops: deployment, bug_finder: static analysis
AGENTS=("pm" "architect" "builder" "reviewer" "tester" "security" "devops" "bug_finder")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    # Check tmux
    if ! command -v tmux &> /dev/null; then
        log_error "tmux is not installed. Please install it first."
        exit 1
    fi
    
    # Check Python venv
    if [ ! -f "${VENV_DIR}/bin/python" ]; then
        log_error "Python virtual environment not found at ${VENV_DIR}"
        log_info "Run 'make install' to create the environment."
        exit 1
    fi
    
    # Check agent runner exists
    if [ ! -f "${AGENT_RUNNER}" ]; then
        log_error "Agent runner not found at ${AGENT_RUNNER}"
        exit 1
    fi
    
    # Ensure log directory exists
    mkdir -p "${LOG_DIR}"
}

is_agent_running() {
    local agent=$1
    tmux has-session -t "claude-${agent}" 2>/dev/null
}

# -----------------------------------------------------------------------------
# Agent Management Functions
# -----------------------------------------------------------------------------

start_agent() {
    local agent=$1
    local session_name="claude-${agent}"
    
    if is_agent_running "${agent}"; then
        log_warning "Agent '${agent}' is already running in tmux session '${session_name}'"
        return 0
    fi
    
    log_info "Starting ${agent} agent..."
    
    # Create tmux session with the agent
    tmux new-session -d -s "${session_name}" \
        "cd ${PROJECT_DIR} && source ${VENV_DIR}/bin/activate && python ${AGENT_RUNNER} --agent ${agent} 2>&1 | tee -a ${LOG_DIR}/${agent}.log"
    
    # Give it a moment to start
    sleep 2
    
    if is_agent_running "${agent}"; then
        log_success "Agent '${agent}' started in tmux session '${session_name}'"
        log_info "  Attach with: tmux attach -t ${session_name}"
        log_info "  Logs at: ${LOG_DIR}/${agent}.log"
    else
        log_error "Failed to start agent '${agent}'"
        return 1
    fi
}

stop_agent() {
    local agent=$1
    local session_name="claude-${agent}"
    
    if ! is_agent_running "${agent}"; then
        log_warning "Agent '${agent}' is not running"
        return 0
    fi
    
    log_info "Stopping ${agent} agent..."
    
    # Send SIGTERM to the process in the tmux session
    tmux send-keys -t "${session_name}" C-c
    sleep 2
    
    # Kill the session if still running
    if is_agent_running "${agent}"; then
        tmux kill-session -t "${session_name}" 2>/dev/null || true
    fi
    
    log_success "Agent '${agent}' stopped"
}

start_all() {
    log_info "Starting all agents..."
    echo ""
    
    for agent in "${AGENTS[@]}"; do
        start_agent "${agent}"
        echo ""
    done
    
    log_success "All agents started!"
    echo ""
    show_status
}

stop_all() {
    log_info "Stopping all agents..."
    echo ""
    
    for agent in "${AGENTS[@]}"; do
        stop_agent "${agent}"
    done
    
    # Also stop master if running
    if is_agent_running "master"; then
        stop_agent "master"
    fi
    
    echo ""
    log_success "All agents stopped"
}

show_status() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "                    AGENT STATUS"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    printf "%-15s %-10s %-30s\n" "AGENT" "STATUS" "SESSION"
    echo "───────────────────────────────────────────────────────────────"
    
    for agent in "${AGENTS[@]}"; do
        if is_agent_running "${agent}"; then
            printf "%-15s ${GREEN}%-10s${NC} %-30s\n" "${agent}" "RUNNING" "claude-${agent}"
        else
            printf "%-15s ${RED}%-10s${NC} %-30s\n" "${agent}" "STOPPED" "-"
        fi
    done
    
    # Check master agent too
    if is_agent_running "master"; then
        printf "%-15s ${GREEN}%-10s${NC} %-30s\n" "master" "RUNNING" "claude-master"
    fi
    
    echo ""
    echo "───────────────────────────────────────────────────────────────"
    echo ""
    echo "Commands:"
    echo "  tmux attach -t claude-{agent}  # Attach to agent session"
    echo "  tmux ls                        # List all sessions"
    echo "  tail -f ${LOG_DIR}/{agent}.log # Watch agent logs"
    echo ""
}

show_help() {
    echo "Multi-Agent Launcher for Autonomous Claude"
    echo ""
    echo "Usage: $0 [command] [agent]"
    echo ""
    echo "Commands:"
    echo "  (no args)       Start all agents (hunter, builder, publisher, liaison, etc.)"
    echo "  hunter          Start only the Hunter agent"
    echo "  builder         Start only the Builder agent"
    echo "  publisher       Start only the Publisher agent"
    echo "  liaison         Start only the Liaison agent (human interface)"
    echo "  master          Start only the Master agent (general purpose)"
    echo "  stop            Stop all running agents"
    echo "  stop <agent>    Stop a specific agent"
    echo "  status          Show status of all agents"
    echo "  help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                    # Start all specialized agents"
    echo "  $0 hunter             # Start only hunter"
    echo "  $0 liaison            # Start only liaison (human interface)"
    echo "  $0 stop               # Stop all agents"
    echo "  $0 stop builder       # Stop only builder"
    echo "  $0 status             # Check agent status"
    echo ""
    echo "Agent Roles:"
    echo "  hunter     - Scans platforms for income opportunities"
    echo "  critic     - Evaluates ideas before development (gatekeeper)"
    echo "  pm         - Creates detailed product specifications"
    echo "  builder    - Creates products, tools, and digital assets"
    echo "  reviewer   - Code review before testing (security, quality)"
    echo "  tester     - QA validation in isolated containers"
    echo "  publisher  - Deploys products and handles marketing"
    echo "  meta       - Swarm architect (creates/modifies agents)"
    echo "  liaison    - Human interface (responds to questions, relays directives)"
    echo "  support    - Monitors GitHub/npm issues and triages feedback"
    echo "  master     - General-purpose agent (handles all tasks)"
    echo ""
}

# -----------------------------------------------------------------------------
# Main Script
# -----------------------------------------------------------------------------

main() {
    check_prerequisites
    
    case "${1:-}" in
        "")
            start_all
            ;;
        "hunter"|"critic"|"pm"|"builder"|"reviewer"|"tester"|"publisher"|"meta"|"liaison"|"support"|"master")
            start_agent "$1"
            ;;
        "stop")
            if [ -n "${2:-}" ]; then
                stop_agent "$2"
            else
                stop_all
            fi
            ;;
        "status")
            show_status
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            log_error "Unknown command: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
