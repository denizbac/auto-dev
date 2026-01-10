#!/bin/bash
# Start the Slack bot service with optional ngrok tunnel
#
# Usage:
#   ./start_slack_bot.sh         # Start bot only (HTTP on port 8081)
#   ./start_slack_bot.sh tunnel  # Start bot + ngrok HTTPS tunnel
#   ./start_slack_bot.sh stop    # Stop both

set -e

BOT_DIR="/autonomous-claude"
BOT_LOG="/autonomous-claude/logs/slack_bot.log"
NGROK_LOG="/autonomous-claude/logs/ngrok.log"

cd "$BOT_DIR"

case "${1:-start}" in
    start)
        echo "Starting Slack bot on port 8081..."
        source venv/bin/activate
        
        # Kill existing if running
        pkill -f "uvicorn dashboard.slack_bot" 2>/dev/null || true
        
        # Start bot in background
        nohup python -m uvicorn dashboard.slack_bot:app --host 0.0.0.0 --port 8081 >> "$BOT_LOG" 2>&1 &
        
        sleep 2
        if curl -s http://localhost:8081/health | grep -q "ok"; then
            echo "✓ Slack bot started on http://localhost:8081"
        else
            echo "✗ Failed to start bot. Check $BOT_LOG"
            exit 1
        fi
        ;;
        
    tunnel)
        echo "Starting Slack bot with ngrok tunnel..."
        
        # Check ngrok auth
        if ! ngrok config check 2>/dev/null | grep -q "valid"; then
            echo "⚠️  ngrok not authenticated. Get your auth token from https://dashboard.ngrok.com/get-started/your-authtoken"
            echo "   Then run: ngrok config add-authtoken YOUR_TOKEN"
            exit 1
        fi
        
        # Start bot first
        $0 start
        
        # Kill existing ngrok
        pkill -f "ngrok http" 2>/dev/null || true
        
        # Start ngrok in background
        echo "Starting ngrok tunnel..."
        nohup ngrok http 8081 --log=stdout >> "$NGROK_LOG" 2>&1 &
        
        # Wait for tunnel to be ready
        sleep 3
        
        # Get the public URL
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print(t[0]['public_url'] if t else '')" 2>/dev/null)
        
        if [ -n "$NGROK_URL" ]; then
            echo ""
            echo "✓ ngrok tunnel active!"
            echo ""
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "  PUBLIC URL: $NGROK_URL"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo ""
            echo "Update your Slack app's slash command URL to:"
            echo "  ${NGROK_URL}/slack/commands"
            echo ""
            echo "Go to: https://api.slack.com/apps → Your App → Slash Commands → Edit"
            echo ""
        else
            echo "⚠️  ngrok started but couldn't get URL. Check $NGROK_LOG"
            echo "    You can also view at http://localhost:4040"
        fi
        ;;
        
    stop)
        echo "Stopping Slack bot and ngrok..."
        pkill -f "uvicorn dashboard.slack_bot" 2>/dev/null && echo "✓ Bot stopped" || echo "Bot wasn't running"
        pkill -f "ngrok http" 2>/dev/null && echo "✓ ngrok stopped" || echo "ngrok wasn't running"
        ;;
        
    status)
        echo "=== Slack Bot Status ==="
        if pgrep -f "uvicorn dashboard.slack_bot" > /dev/null; then
            echo "Bot: RUNNING"
            curl -s http://localhost:8081/health 2>/dev/null || echo "(health check failed)"
        else
            echo "Bot: STOPPED"
        fi
        
        echo ""
        if pgrep -f "ngrok http" > /dev/null; then
            echo "ngrok: RUNNING"
            NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print(t[0]['public_url'] if t else 'unknown')" 2>/dev/null)
            echo "  URL: $NGROK_URL"
        else
            echo "ngrok: STOPPED"
        fi
        ;;
        
    url)
        # Just print the current ngrok URL
        NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; t=json.load(sys.stdin)['tunnels']; print(t[0]['public_url'] if t else '')" 2>/dev/null)
        if [ -n "$NGROK_URL" ]; then
            echo "${NGROK_URL}/slack/commands"
        else
            echo "ngrok not running"
            exit 1
        fi
        ;;
        
    *)
        echo "Usage: $0 {start|tunnel|stop|status|url}"
        echo ""
        echo "  start   - Start bot on port 8081 (HTTP only)"
        echo "  tunnel  - Start bot + ngrok HTTPS tunnel"
        echo "  stop    - Stop bot and ngrok"
        echo "  status  - Show current status"
        echo "  url     - Print current ngrok URL"
        exit 1
        ;;
esac

