#!/usr/bin/env python3
"""
Demo: 用 fine-grained PAT 读 GitHub PR 的 CI 状态。

策略（fine-grained PAT 体系下）：
  1) GET /repos/{owner}/{repo}/actions/runs?head_sha=SHA  → 拿 GitHub Actions 状态
  2) GET /repos/{owner}/{repo}/commits/{sha}/status       → 拿外部 CI 的 combined status
  3) 两路 AND 判定 all_checks_green

权限要求：
  - Actions: Read-only
  - Commit statuses: Read-only
  - Metadata: Read-only (强制)
  - Pull requests: Read-only (用于读 PR head sha)
"""

import os
import sys
import time
import json
import argparse
from typing import Optional
from urllib import request, parse, error

GH_API = "https://api.github.com"
GREEN = {"success", "skipped", "neutral"}


def gh_get(path: str, token: str, params: Optional[dict] = None) -> dict:
    url = f"{GH_API}{path}"
    if params:
        url += "?" + parse.urlencode(params)
    req = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ci-status-demo/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        # 把权限提示 header 抓出来打印，便于排查
        accepted = e.headers.get("x-accepted-github-permissions", "")
        print(f"❌ HTTP {e.code} for {url}\n   body: {body[:300]}\n   x-accepted: {accepted}", file=sys.stderr)
        raise


def get_pr_head_sha(owner: str, repo: str, pr: int, token: str) -> str:
    data = gh_get(f"/repos/{owner}/{repo}/pulls/{pr}", token)
    return data["head"]["sha"]


def get_actions_status(owner: str, repo: str, sha: str, token: str) -> dict:
    data = gh_get(
        f"/repos/{owner}/{repo}/actions/runs",
        token,
        params={"head_sha": sha, "per_page": "100"},
    )
    runs = data.get("workflow_runs", [])
    if not runs:
        return {"has_runs": False, "all_green": True, "pending": False, "runs": []}

    pending = any(r["status"] != "completed" for r in runs)
    all_green = all(
        r["status"] == "completed" and r["conclusion"] in GREEN for r in runs
    )
    return {
        "has_runs": True,
        "all_green": all_green and not pending,
        "pending": pending,
        "runs": [
            {
                "name": r["name"],
                "status": r["status"],
                "conclusion": r["conclusion"],
                "url": r["html_url"],
            }
            for r in runs
        ],
    }


def get_combined_status(owner: str, repo: str, sha: str, token: str) -> dict:
    data = gh_get(f"/repos/{owner}/{repo}/commits/{sha}/status", token)
    return {
        "has_statuses": data["total_count"] > 0,
        "state": data["state"],
        "all_green": data["total_count"] == 0 or data["state"] == "success",
        "contexts": [
            {"context": s["context"], "state": s["state"]}
            for s in data.get("statuses", [])
        ],
    }


def is_ci_green(owner: str, repo: str, sha: str, token: str) -> dict:
    actions = get_actions_status(owner, repo, sha, token)
    statuses = get_combined_status(owner, repo, sha, token)
    # 注意：当 has_statuses=False 时，combined state 会返回 "pending"
    # （"pending if there are no statuses"），那不是真 pending。
    statuses_pending = statuses["has_statuses"] and statuses["state"] == "pending"
    return {
        "all_checks_green": actions["all_green"] and statuses["all_green"],
        "pending": actions["pending"] or statuses_pending,
        "actions": actions,
        "statuses": statuses,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--poll", action="store_true", help="poll until CI completes")
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN")
    if not token:
        print("ERROR: set GH_TOKEN env var", file=sys.stderr)
        sys.exit(2)

    sha = get_pr_head_sha(args.owner, args.repo, args.pr, token)
    print(f"PR #{args.pr} head_sha = {sha}\n")

    deadline = time.time() + args.timeout
    while True:
        result = is_ci_green(args.owner, args.repo, sha, token)
        print(json.dumps(result, indent=2))
        print("-" * 60)

        if not args.poll:
            break
        if not result["pending"]:
            print(f"\n✅ CI completed. all_checks_green = {result['all_checks_green']}")
            sys.exit(0 if result["all_checks_green"] else 1)
        if time.time() > deadline:
            print("\n⏱  timeout", file=sys.stderr)
            sys.exit(3)

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
