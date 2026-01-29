#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _get_env(name: str, required: bool = True) -> str:
    value = os.getenv(name)
    if required and not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value or ""


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise SystemExit(f"Task API error ({e.code}): {body}") from e


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an Auto-Dev task via dashboard API.")
    parser.add_argument("--agent", required=True, help="Target agent id (e.g., architect)")
    parser.add_argument("--task-type", required=True, help="Task type (e.g., analyze_repo)")
    parser.add_argument("--priority", type=int, default=5, help="Priority 1-10")
    parser.add_argument("--repo-id", help="Repo id for the task")
    parser.add_argument("--parent-task-id", help="Parent task id for linking")
    parser.add_argument("--instruction", help="Task instruction (stored in payload)")
    parser.add_argument("--payload-json", help="Full payload as JSON string")
    parser.add_argument("--created-by", default="pm", help="created_by value")
    parser.add_argument("--dashboard-url", help="Dashboard base URL (default from DASHBOARD_URL)")

    args = parser.parse_args()

    dashboard_url = args.dashboard_url or os.getenv("DASHBOARD_URL") or "http://auto-dev-dashboard:8080"
    endpoint = dashboard_url.rstrip("/") + "/api/tasks"

    payload: dict = {}
    if args.payload_json:
        try:
            payload = json.loads(args.payload_json)
        except json.JSONDecodeError as e:
            raise SystemExit(f"Invalid --payload-json: {e}") from e
    if args.instruction:
        payload["instruction"] = args.instruction
    if args.repo_id:
        payload["repo_id"] = args.repo_id

    req = {
        "type": args.task_type,
        "to": args.agent,
        "priority": int(args.priority),
        "payload": payload,
        "created_by": args.created_by,
    }
    if args.repo_id:
        req["repo_id"] = args.repo_id
    if args.parent_task_id:
        req["parent_task_id"] = args.parent_task_id

    response = _post_json(endpoint, req)
    print(json.dumps(response, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
