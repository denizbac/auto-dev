#!/usr/bin/env python3
import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

import psycopg2


def _get_env(name: str, required: bool = True) -> str:
    value = os.getenv(name)
    if required and not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value or ""


def _encode_id(value: str) -> str:
    if value.isdigit():
        return value
    return urllib.parse.quote(value, safe="")


def _fetch_repo(repo_id: str | None, slug: str | None, name: str | None) -> dict:
    db_host = _get_env("DB_HOST")
    db_name = _get_env("DB_NAME")
    db_user = _get_env("DB_USER")
    db_pass = _get_env("DB_PASSWORD")
    db_port = os.getenv("DB_PORT", "5432")

    if not any([repo_id, slug, name]):
        raise SystemExit("Provide one of --repo-id, --repo-slug, or --repo-name.")

    query = "SELECT id, name, gitlab_url, gitlab_project_id, provider, settings FROM repos WHERE "
    params = []
    clauses = []
    if repo_id:
        clauses.append("id = %s")
        params.append(repo_id)
    if slug:
        clauses.append("slug = %s")
        params.append(slug)
    if name:
        clauses.append("name = %s")
        params.append(name)
    query += " OR ".join(clauses)
    query += " LIMIT 1"

    with psycopg2.connect(
        host=db_host, dbname=db_name, user=db_user, password=db_pass, port=db_port
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()

    if not row:
        raise SystemExit("Repo not found in database.")

    settings = row[5] or "{}"
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            settings = {}
    elif settings is None:
        settings = {}

    return {
        "id": row[0],
        "name": row[1],
        "gitlab_url": row[2],
        "gitlab_project_id": row[3],
        "provider": row[4],
        "settings": settings,
    }


def _update_repo_settings(repo_id: str, settings: dict) -> None:
    db_host = _get_env("DB_HOST")
    db_name = _get_env("DB_NAME")
    db_user = _get_env("DB_USER")
    db_pass = _get_env("DB_PASSWORD")
    db_port = os.getenv("DB_PORT", "5432")

    with psycopg2.connect(
        host=db_host, dbname=db_name, user=db_user, password=db_pass, port=db_port
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE repos SET settings = %s WHERE id = %s",
                (json.dumps(settings), repo_id),
            )
        conn.commit()


def _request(method: str, url: str, token: str, payload: dict | None = None) -> dict | list:
    data = None
    headers = {"PRIVATE-TOKEN": token}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise SystemExit(f"GitLab API error ({e.code}): {body}") from e


def _resolve_project(args: argparse.Namespace) -> tuple[str, str]:
    if args.repo_id or args.repo_slug or args.repo_name:
        repo = _fetch_repo(args.repo_id, args.repo_slug, args.repo_name)
        if repo["provider"] != "gitlab":
            raise SystemExit(f"Repo provider is '{repo['provider']}', not gitlab.")
        return repo["gitlab_url"], repo["gitlab_project_id"]

    if args.project_id:
        gitlab_url = args.gitlab_url or os.getenv("GITLAB_URL")
        if not gitlab_url:
            raise SystemExit("Missing --gitlab-url (or GITLAB_URL) with --project-id.")
        return gitlab_url, args.project_id

    raise SystemExit("Provide repo selector or --project-id/--gitlab-url.")


def _resolve_group(args: argparse.Namespace) -> tuple[str, str]:
    gitlab_url = args.gitlab_url or os.getenv("GITLAB_URL")
    if not gitlab_url:
        raise SystemExit("Missing --gitlab-url (or GITLAB_URL) for epics.")

    group = args.group_id or args.group_path or os.getenv("GITLAB_GROUP_ID") or os.getenv("GITLAB_GROUP_PATH")
    if not group:
        raise SystemExit("Missing --group-id/--group-path (or GITLAB_GROUP_ID/GITLAB_GROUP_PATH) for epics.")

    return gitlab_url, group


def issue_create(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, project_id = _resolve_project(args)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/projects/{_encode_id(project_id)}/issues"
    payload = {"title": args.title, "description": args.description}
    if args.labels:
        payload["labels"] = args.labels
    if args.dry_run:
        print(json.dumps({"endpoint": endpoint, "payload": payload}, indent=2))
        return
    issue = _request("POST", endpoint, token, payload)
    print(json.dumps({"iid": issue.get("iid"), "web_url": issue.get("web_url")}, indent=2))


def issue_get(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, project_id = _resolve_project(args)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/projects/{_encode_id(project_id)}/issues/{args.iid}"
    issue = _request("GET", endpoint, token)
    print(json.dumps(issue, indent=2))


def issue_list(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, project_id = _resolve_project(args)
    params = {}
    if args.state:
        params["state"] = args.state
    if args.search:
        params["search"] = args.search
    if args.labels:
        params["labels"] = args.labels
    if args.per_page:
        params["per_page"] = str(args.per_page)
    if args.page:
        params["page"] = str(args.page)

    query = urllib.parse.urlencode(params)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/projects/{_encode_id(project_id)}/issues"
    if query:
        endpoint = f"{endpoint}?{query}"
    issues = _request("GET", endpoint, token)
    print(json.dumps(issues, indent=2))


def issue_update(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, project_id = _resolve_project(args)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/projects/{_encode_id(project_id)}/issues/{args.iid}"
    payload: dict[str, str] = {}
    if args.title:
        payload["title"] = args.title
    if args.description:
        payload["description"] = args.description
    if args.labels:
        payload["labels"] = args.labels
    if args.add_labels:
        payload["add_labels"] = args.add_labels
    if args.remove_labels:
        payload["remove_labels"] = args.remove_labels
    if args.state:
        payload["state_event"] = args.state
    if not payload:
        raise SystemExit("No update fields provided.")
    if args.dry_run:
        print(json.dumps({"endpoint": endpoint, "payload": payload}, indent=2))
        return
    issue = _request("PUT", endpoint, token, payload)
    print(json.dumps({"iid": issue.get("iid"), "web_url": issue.get("web_url")}, indent=2))


def issue_comment(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, project_id = _resolve_project(args)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/projects/{_encode_id(project_id)}/issues/{args.iid}/notes"
    payload = {"body": args.body}
    if args.dry_run:
        print(json.dumps({"endpoint": endpoint, "payload": payload}, indent=2))
        return
    note = _request("POST", endpoint, token, payload)
    print(json.dumps({"id": note.get("id"), "body": note.get("body")}, indent=2))

def epic_create(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, group = _resolve_group(args)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/groups/{_encode_id(group)}/epics"
    payload = {"title": args.title, "description": args.description}
    if args.labels:
        payload["labels"] = args.labels
    if args.dry_run:
        print(json.dumps({"endpoint": endpoint, "payload": payload}, indent=2))
        return
    epic = _request("POST", endpoint, token, payload)
    print(json.dumps({"iid": epic.get("iid"), "web_url": epic.get("web_url")}, indent=2))


def epic_get(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, group = _resolve_group(args)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/groups/{_encode_id(group)}/epics/{args.iid}"
    epic = _request("GET", endpoint, token)
    print(json.dumps(epic, indent=2))


def epic_list(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, group = _resolve_group(args)
    params = {}
    if args.state:
        params["state"] = args.state
    if args.search:
        params["search"] = args.search
    if args.labels:
        params["labels"] = args.labels
    if args.per_page:
        params["per_page"] = str(args.per_page)
    if args.page:
        params["page"] = str(args.page)

    query = urllib.parse.urlencode(params)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/groups/{_encode_id(group)}/epics"
    if query:
        endpoint = f"{endpoint}?{query}"
    epics = _request("GET", endpoint, token)
    print(json.dumps(epics, indent=2))


def webhook_list(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    gitlab_url, project_id = _resolve_project(args)
    endpoint = f"{gitlab_url.rstrip('/')}/api/v4/projects/{_encode_id(project_id)}/hooks"
    hooks = _request("GET", endpoint, token)
    print(json.dumps(hooks, indent=2))


def webhook_ensure(args: argparse.Namespace) -> None:
    token = _get_env("GITLAB_TOKEN")
    repo = _fetch_repo(
        args.repo_id,
        getattr(args, "repo_slug", None),
        getattr(args, "repo_name", None),
    )
    if repo["provider"] != "gitlab":
        raise SystemExit(f"Repo provider is '{repo['provider']}', not gitlab.")

    auto_dev_url = _get_env("AUTO_DEV_URL")
    webhook_url = auto_dev_url.rstrip("/") + "/webhook/gitlab"

    settings = repo["settings"] or {}
    secret = settings.get("webhook_secret")
    if not secret or args.regenerate:
        secret = secrets.token_hex(32)
        settings["webhook_secret"] = secret
        _update_repo_settings(repo["id"], settings)

    # List existing hooks and reuse if present
    endpoint = f"{repo['gitlab_url'].rstrip('/')}/api/v4/projects/{_encode_id(repo['gitlab_project_id'])}/hooks"
    hooks = _request("GET", endpoint, token)
    existing = None
    for hook in hooks:
        if hook.get("url") == webhook_url:
            existing = hook
            break

    payload = {
        "url": webhook_url,
        "token": secret,
        "push_events": True,
        "issues_events": True,
        "merge_requests_events": True,
        "note_events": True,
        "pipeline_events": True,
    }

    if existing and not args.regenerate:
        print(json.dumps({"status": "exists", "id": existing.get("id"), "url": webhook_url}, indent=2))
        return

    if existing and args.regenerate:
        hook_id = existing.get("id")
        update_url = f"{endpoint}/{hook_id}"
        hook = _request("PUT", update_url, token, payload)
        print(json.dumps({"status": "updated", "id": hook.get("id"), "url": hook.get("url")}, indent=2))
        return

    hook = _request("POST", endpoint, token, payload)
    print(json.dumps({"status": "created", "id": hook.get("id"), "url": hook.get("url")}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="GitLab helper for Auto-Dev agents.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_repo_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo-id")
        p.add_argument("--repo-slug")
        p.add_argument("--repo-name")
        p.add_argument("--project-id")
        p.add_argument("--gitlab-url")

    issue_create_p = sub.add_parser("issue-create", help="Create a GitLab issue")
    add_repo_args(issue_create_p)
    issue_create_p.add_argument("--title", required=True)
    issue_create_p.add_argument("--description", required=True)
    issue_create_p.add_argument("--labels", default="")
    issue_create_p.add_argument("--dry-run", action="store_true")
    issue_create_p.set_defaults(func=issue_create)

    issue_get_p = sub.add_parser("issue-get", help="Get a GitLab issue by IID")
    add_repo_args(issue_get_p)
    issue_get_p.add_argument("--iid", required=True)
    issue_get_p.set_defaults(func=issue_get)

    issue_list_p = sub.add_parser("issue-list", help="List GitLab issues")
    add_repo_args(issue_list_p)
    issue_list_p.add_argument("--state", choices=["opened", "closed", "all"])
    issue_list_p.add_argument("--search")
    issue_list_p.add_argument("--labels")
    issue_list_p.add_argument("--per-page", type=int, default=20)
    issue_list_p.add_argument("--page", type=int, default=1)
    issue_list_p.set_defaults(func=issue_list)

    issue_update_p = sub.add_parser("issue-update", help="Update a GitLab issue")
    add_repo_args(issue_update_p)
    issue_update_p.add_argument("--iid", required=True)
    issue_update_p.add_argument("--title")
    issue_update_p.add_argument("--description")
    issue_update_p.add_argument("--labels", default="")
    issue_update_p.add_argument("--add-labels", default="")
    issue_update_p.add_argument("--remove-labels", default="")
    issue_update_p.add_argument("--state", choices=["close", "reopen"])
    issue_update_p.add_argument("--dry-run", action="store_true")
    issue_update_p.set_defaults(func=issue_update)

    issue_comment_p = sub.add_parser("issue-comment", help="Add a comment to a GitLab issue")
    add_repo_args(issue_comment_p)
    issue_comment_p.add_argument("--iid", required=True)
    issue_comment_p.add_argument("--body", required=True)
    issue_comment_p.add_argument("--dry-run", action="store_true")
    issue_comment_p.set_defaults(func=issue_comment)

    epic_create_p = sub.add_parser("epic-create", help="Create a GitLab epic (group-level)")
    epic_create_p.add_argument("--group-id")
    epic_create_p.add_argument("--group-path")
    epic_create_p.add_argument("--gitlab-url")
    epic_create_p.add_argument("--title", required=True)
    epic_create_p.add_argument("--description", required=True)
    epic_create_p.add_argument("--labels", default="")
    epic_create_p.add_argument("--dry-run", action="store_true")
    epic_create_p.set_defaults(func=epic_create)

    epic_get_p = sub.add_parser("epic-get", help="Get a GitLab epic by IID (group-level)")
    epic_get_p.add_argument("--group-id")
    epic_get_p.add_argument("--group-path")
    epic_get_p.add_argument("--gitlab-url")
    epic_get_p.add_argument("--iid", required=True)
    epic_get_p.set_defaults(func=epic_get)

    epic_list_p = sub.add_parser("epic-list", help="List GitLab epics (group-level)")
    epic_list_p.add_argument("--group-id")
    epic_list_p.add_argument("--group-path")
    epic_list_p.add_argument("--gitlab-url")
    epic_list_p.add_argument("--state", choices=["opened", "closed", "all"])
    epic_list_p.add_argument("--search")
    epic_list_p.add_argument("--labels")
    epic_list_p.add_argument("--per-page", type=int, default=20)
    epic_list_p.add_argument("--page", type=int, default=1)
    epic_list_p.set_defaults(func=epic_list)

    webhook_list_p = sub.add_parser("webhook-list", help="List GitLab project webhooks")
    add_repo_args(webhook_list_p)
    webhook_list_p.set_defaults(func=webhook_list)

    webhook_ensure_p = sub.add_parser("webhook-ensure", help="Create or update GitLab webhook")
    webhook_ensure_p.add_argument("--repo-id", required=True)
    webhook_ensure_p.add_argument("--regenerate", action="store_true")
    webhook_ensure_p.set_defaults(func=webhook_ensure)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
