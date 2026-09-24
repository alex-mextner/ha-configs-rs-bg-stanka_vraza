#!/usr/bin/env bash
# Full apply cycle for a fork-tracked HACS submodule integration:
#   1. fast-forward the submodule to the latest commit on its "myfork" remote
#      (which a GitHub Action keeps rebased onto upstream + tagged with a
#      matching release, see .github/workflows/sync-upstream.yml in the fork).
#   2. rsync the submodule content into custom_components/<domain> (never a
#      symlink -- see sync-submodule-to-custom-components.sh).
#   3. point HACS at the fork (full_name) and sync version_installed /
#      installed_commit so the phantom "update available" never appears --
#      this is the ONLY supported way to apply an update; HACS's own "Update"
#      button in the UI is not a valid path for these repos (see AGENTS.md).
#   4. docker kill+start homeassistant-homeassistant-1 (NOT graceful restart --
#      HA rewrites .storage on graceful shutdown, wiping the hand-edit).
#
# Usage: apply-fork-update.sh <submodule-name> <fork-full-name> <fork-branch>
# Example: apply-fork-update.sh YandexStation alex-mextner/YandexStation master
set -euo pipefail

HA_ROOT="/home/ultra/homeassistant"
CONTAINER="homeassistant-homeassistant-1"

SUBMODULE="${1:?usage: apply-fork-update.sh <submodule> <fork-full-name> <fork-branch>}"
FORK_FULL_NAME="${2:?missing fork full_name (owner/repo)}"
FORK_BRANCH="${3:?missing fork branch}"

cd "$HA_ROOT/submodules/$SUBMODULE"
echo "== fetching myfork =="
git fetch myfork
BEFORE=$(git rev-parse HEAD)
TARGET=$(git rev-parse "myfork/$FORK_BRANCH")
if [ "$BEFORE" = "$TARGET" ]; then
  echo "already at myfork/$FORK_BRANCH ($TARGET) -- nothing to fast-forward"
else
  # The fork CI rebases onto upstream and force-pushes, so fast-forward never
  # works; take the fork branch as-is.
  git checkout -B "$FORK_BRANCH" "myfork/$FORK_BRANCH"
  echo "fast-forwarded $BEFORE -> $TARGET"
fi

echo "== syncing custom_components =="
"$HA_ROOT/scripts/sync-submodule-to-custom-components.sh" "$SUBMODULE"

VERSION=$(git -C "$HA_ROOT/submodules/$SUBMODULE" describe --tags --abbrev=0 2>/dev/null || echo "")
COMMIT=$(git -C "$HA_ROOT/submodules/$SUBMODULE" rev-parse --short HEAD)

echo "== syncing HACS storage (point at fork, clear phantom) =="
docker exec -i "$CONTAINER" python3 - "$FORK_FULL_NAME" "$VERSION" "$COMMIT" <<'PYEOF'
import json, sys
fork_full_name, version, commit = sys.argv[1], sys.argv[2], sys.argv[3]
p = "/config/.storage/hacs.repositories"
d = json.load(open(p))
data = d["data"]
found = None
for rid, r in data.items():
    fn = r.get("full_name", "")
    if fn.lower() == fork_full_name.lower() or "yandexstation" in fn.lower():
        found = rid
        break
if not found:
    raise SystemExit("repo not found in hacs.repositories")
r = data[found]
r["full_name"] = fork_full_name
r["version_installed"] = version
r["installed_commit"] = commit
r["last_version"] = version
r["last_commit"] = commit
print(found, "->", r["full_name"], r["version_installed"], r["installed_commit"])
json.dump(d, open(p, "w"))
PYEOF

echo "== applying without graceful shutdown =="
docker kill "$CONTAINER"
docker start "$CONTAINER"
echo "done -- wait for container healthy, then verify update.<domain>_update is off"
