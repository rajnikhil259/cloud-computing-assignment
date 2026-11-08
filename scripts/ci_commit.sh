#!/usr/bin/env bash
# Commit result files from a GitHub Actions job and push them to the current branch.
# Commits are authored by the repository owner (never by a bot account).
#   scripts/ci_commit.sh "message" path [path ...]
set -euo pipefail
msg="$1"; shift
owner="${GITHUB_REPOSITORY_OWNER:?}"
owner_id="${REPO_OWNER_ID:?set REPO_OWNER_ID to github.repository_owner_id}"
git config user.name "$owner"
git config user.email "${owner_id}+${owner}@users.noreply.github.com"
git add -A -- "$@"
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$msg"
branch="${GITHUB_REF_NAME:?}"
for i in 1 2 3 4 5; do
  if git pull -q --rebase origin "$branch" && git push -q origin "HEAD:$branch"; then
    git log -1 --format='pushed %h by %an <%ae>: %s'
    exit 0
  fi
  sleep $((i * 5))
done
echo "push failed" >&2
exit 1
