#!/usr/bin/env python3
"""
Bot: 轮询 PR 的 CI 状态，全绿且 mergeable_state=clean 后自动 merge。

设计：
  - 用 fine-grained PAT (READ_TOKEN) 读 CI 状态 (Actions + Commit statuses + PR meta)
  - 用 write-capable token (WRITE_TOKEN) 真正触发 merge
  - 两 token 分离 = 最小权限 / 职责分离

依赖：仅 stdlib。
"""

import os
import sys
import time
import json
import argparse
from urllib import request, parse, error

GH_API = "https://api.github.com"
GREEN = {"success", "skipped", "neutral"}


def gh_request(method, path, token, body=None):
    url = f"{GH_API}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ci-bot-demo/1.0",
            "Content-Type": "application/json" if body else "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            payload = resp.read()
            return resp.status, json.loads(payload) if payload else {}
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}


def get_pr(owner, repo, pr, token):
    code, data = gh_request("GET", f"/repos/{owner}/{repo}/pulls/{pr}", token)
    if code != 200:
        raise RuntimeError(f"get_pr failed: {code} {data}")
    return data


def get_actions_runs(owner, repo, sha, token):
    code, data = gh_request(
        "GET",
        f"/repos/{owner}/{repo}/actions/runs?head_sha={sha}&per_page=100",
        token,
    )
    if code != 200:
        raise RuntimeError(f"get_actions_runs failed: {code} {data}")
    return data.get("workflow_runs", [])


def get_combined_status(owner, repo, sha, token):
    code, data = gh_request(
        "GET", f"/repos/{owner}/{repo}/commits/{sha}/status", token
    )
    if code != 200:
        raise RuntimeError(f"get_combined_status failed: {code} {data}")
    return data


def evaluate(owner, repo, pr, read_token):
    """返回 (ready_to_merge, reason, snapshot)。"""
    pr_data = get_pr(owner, repo, pr, read_token)
    sha = pr_data["head"]["sha"]

    runs = get_actions_runs(owner, repo, sha, read_token)
    statuses = get_combined_status(owner, repo, sha, read_token)

    # CI 完成判定
    actions_pending = any(r["status"] != "completed" for r in runs)
    actions_green = (
        len(runs) > 0
        and not actions_pending
        and all(r["conclusion"] in GREEN for r in runs)
    )
    statuses_pending = statuses["total_count"] > 0 and statuses["state"] == "pending"
    statuses_green = statuses["total_count"] == 0 or statuses["state"] == "success"

    snapshot = {
        "pr": pr,
        "sha": sha[:7],
        "state": pr_data["state"],
        "mergeable": pr_data["mergeable"],
        "mergeable_state": pr_data["mergeable_state"],
        "actions": [
            {"name": r["name"], "status": r["status"], "conclusion": r["conclusion"]}
            for r in runs
        ],
        "combined_status": statuses["state"],
        "combined_total": statuses["total_count"],
    }

    if pr_data["state"] != "open":
        return False, f"PR not open (state={pr_data['state']})", snapshot
    if actions_pending or statuses_pending:
        return False, "CI still running", snapshot
    if not (actions_green and statuses_green):
        return False, "CI not all green", snapshot
    if pr_data["mergeable"] is None:
        return False, "mergeable is null (GitHub computing)", snapshot
    if pr_data["mergeable_state"] != "clean":
        return False, f"mergeable_state={pr_data['mergeable_state']}", snapshot

    return True, "✅ ready to merge", snapshot


def do_merge(owner, repo, pr, write_token, method="squash"):
    code, data = gh_request(
        "PUT",
        f"/repos/{owner}/{repo}/pulls/{pr}/merge",
        write_token,
        body={
            "merge_method": method,
            "commit_title": f"Bot merge PR #{pr}",
            "commit_message": "Merged by ci-bot after all checks passed.",
        },
    )
    return code, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--method", default="squash", choices=["squash", "merge", "rebase"])
    ap.add_argument("--dry-run", action="store_true", help="不实际 merge，只判定")
    args = ap.parse_args()

    read_token = os.environ.get("READ_TOKEN") or os.environ.get("GH_TOKEN")
    write_token = os.environ.get("WRITE_TOKEN") or read_token
    if not read_token:
        print("ERROR: set READ_TOKEN (and optionally WRITE_TOKEN) env", file=sys.stderr)
        sys.exit(2)

    print(f"🤖 Bot watching {args.owner}/{args.repo}#{args.pr}")
    print(f"   read  token: ***{read_token[-6:]}")
    print(f"   write token: ***{write_token[-6:]}")
    print()

    deadline = time.time() + args.timeout
    poll_n = 0
    while True:
        poll_n += 1
        try:
            ready, reason, snap = evaluate(
                args.owner, args.repo, args.pr, read_token
            )
        except Exception as e:
            print(f"[poll {poll_n}] error: {e}")
            time.sleep(args.interval)
            continue

        ts = time.strftime("%H:%M:%S")
        print(f"[{ts} poll {poll_n}] {reason}")
        print(f"   sha={snap['sha']} mergeable={snap['mergeable']} "
              f"mergeable_state={snap['mergeable_state']}")
        for a in snap["actions"]:
            print(f"   action: {a['name']:<10s} status={a['status']:<11s} "
                  f"conclusion={a['conclusion']}")
        print(f"   combined: state={snap['combined_status']} "
              f"total={snap['combined_total']}")

        if ready:
            if args.dry_run:
                print("\n🔵 [dry-run] would merge now.")
                sys.exit(0)
            print(f"\n🚀 Merging via method='{args.method}' ...")
            code, data = do_merge(
                args.owner, args.repo, args.pr, write_token, args.method
            )
            print(f"   HTTP {code}")
            print(f"   response: {json.dumps(data, indent=2)[:400]}")
            sys.exit(0 if code == 200 else 1)

        if time.time() > deadline:
            print("\n⏱  timeout")
            sys.exit(3)

        print(f"   ⏳ sleep {args.interval}s\n")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
