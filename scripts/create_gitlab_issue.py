#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

import psycopg2


def _get_env(name: str, required: bool = True) -> str:
    value = os.getenv(name)
    if required and not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value or ""


def _fetch_repo(repo_id: str | None, slug: str | None, name: str | None) -> dict:
    db_host = _get_env("DB_HOST")
    db_name = _get_env("DB_NAME")
    db_user = _get_env("DB_USER")
    db_pass = _get_env("DB_PASSWORD")
    db_port = os.getenv("DB_PORT", "5432")

    if not any([repo_id, slug, name]):
        raise SystemExit("Provide one of --repo-id, --repo-slug, or --repo-name.")

    query = "SELECT id, name, gitlab_url, gitlab_project_id, provider FROM repos WHERE "
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

    return {
        "id": row[0],
        "name": row[1],
        "gitlab_url": row[2],
        "gitlab_project_id": row[3],
        "provider": row[4],
    }


def _encode_project(project_id: str) -> str:
    if project_id.isdigit():
        return project_id
    return urllib.parse.quote(project_id, safe="")


def _post_issue(gitlab_url: str, project_id: str, token: str, payload: dict) -> dict:
    api_base = gitlab_url.rstrip("/") + "/api/v4"
    endpoint = f"{api_base}/projects/{_encode_project(project_id)}/issues"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a GitLab issue for a configured repo.")
    parser.add_argument("--repo-id", help="Repo ID from Auto-Dev (UUID)")
    parser.add_argument("--repo-slug", help="Repo slug from Auto-Dev")
    parser.add_argument("--repo-name", help="Repo name from Auto-Dev")
    parser.add_argument("--title", required=True, help="Issue title")
    parser.add_argument("--description", required=True, help="Issue description (markdown)")
    parser.add_argument("--labels", default="", help="Comma-separated labels")
    parser.add_argument("--dry-run", action="store_true", help="Print payload and exit")
    args = parser.parse_args()

    token = _get_env("GITLAB_TOKEN")
    repo = _fetch_repo(args.repo_id, args.repo_slug, args.repo_name)

    if repo["provider"] != "gitlab":
        raise SystemExit(f"Repo provider is '{repo['provider']}', not gitlab.")

    payload = {
        "title": args.title,
        "description": args.description,
    }
    if args.labels:
        payload["labels"] = args.labels

    if args.dry_run:
        print(json.dumps({"repo": repo, "payload": payload}, indent=2))
        return 0

    issue = _post_issue(repo["gitlab_url"], repo["gitlab_project_id"], token, payload)
    if not issue:
        raise SystemExit("Issue creation returned no response.")

    web_url = issue.get("web_url") or issue.get("url") or ""
    iid = issue.get("iid", "")
    print(json.dumps({"issue_iid": iid, "web_url": web_url}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
