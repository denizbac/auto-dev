import json
from pathlib import Path

def write_status(state, config):
    status = {
        'is_running': state.is_running,
        'current_session': {
            'id': state.current_session.session_id if state.current_session else None,
            'start_time': str(state.current_session.start_time) if state.current_session else None,
        } if state.current_session else None,
        'total_sessions': state.total_sessions,
        'total_tokens_today': state.total_tokens_today,
        'total_income_today': state.total_income_today,
        'consecutive_failures': state.consecutive_failures,
        'last_restart': str(state.last_restart) if state.last_restart else None,
        'token_budget': {
            'daily_limit': config['tokens']['daily_budget'],
            'used': state.total_tokens_today,
            'remaining': config['tokens']['daily_budget'] - state.total_tokens_today
        }
    }
    Path('/auto-dev/data/watcher_status.json').write_text(json.dumps(status))
