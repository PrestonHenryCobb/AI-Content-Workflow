#!/usr/bin/env bash
# Persist pipeline state between GitHub Actions runs, with no cloud bucket needed.
#   state.sh pull   restore data/ from the `state` branch + buffered videos from the
#                   `buffer` release
#   state.sh push   save data/ (DB, published list, small job JSON) to the `state` branch
#                   (single squashed commit) and upload new buffered videos to the release;
#                   delete release assets for videos that were already used
# Needs: git, gh, GITHUB_TOKEN with contents:write.
set -euo pipefail
cmd="${1:?pull|push}"
REL="buffer"
mkdir -p data/jobs

if [ "$cmd" = "pull" ]; then
  if git fetch -q origin state 2>/dev/null; then
    git archive origin/state data | tar -x
    echo "restored data/ from state branch"
  else
    echo "no state branch yet (first run)"
  fi
  if gh release view "$REL" >/dev/null 2>&1; then
    for a in $(gh release view "$REL" --json assets -q '.assets[].name'); do
      job="${a%.mp4}"
      if [ -d "data/jobs/$job" ] && [ ! -f "data/jobs/$job/short.mp4" ]; then
        gh release download "$REL" -p "$a" -O "data/jobs/$job/short.mp4"
      fi
    done
  fi
  exit 0
fi

if [ "$cmd" = "push" ]; then
  # 1) videos: upload buffered ones, remove used ones
  gh release view "$REL" >/dev/null 2>&1 || \
    gh release create "$REL" --title "Video buffer (managed by pipeline)" \
      --notes "Spare QA-passed shorts waiting for a slot. Managed automatically." --prerelease
  have=$(gh release view "$REL" --json assets -q '.assets[].name' || true)
  buffered=$(sqlite3 data/state.db "SELECT job_id FROM buffer WHERE used_at IS NULL" 2>/dev/null || true)
  for job in $buffered; do
    f="data/jobs/$job/short.mp4"
    if [ -f "$f" ] && ! grep -qx "$job.mp4" <<<"$have"; then
      cp "$f" "/tmp/$job.mp4" && gh release upload "$REL" "/tmp/$job.mp4" --clobber
    fi
  done
  for a in $have; do
    grep -qx "${a%.mp4}" <<<"$buffered" || gh release delete-asset "$REL" "$a" -y || true
  done
  # 2) small state files -> orphan branch, one commit (no history growth)
  tmp=$(mktemp -d)
  mkdir -p "$tmp/data/jobs"
  cp data/state.db data/published_cases.json "$tmp/data/" 2>/dev/null || true
  # keep JSON (+ stills, small PNGs) for buffered jobs and for anything from the last 8 days,
  # which the Sunday compilation re-uses
  recent=$(sqlite3 data/state.db "SELECT job_id FROM jobs WHERE status='done' AND updated_at >= datetime('now','-8 days')" 2>/dev/null || true)
  for job in $(printf "%s\n%s\n" "$buffered" "$recent" | sort -u); do
    if [ -d "data/jobs/$job" ]; then
      mkdir -p "$tmp/data/jobs/$job"
      cp data/jobs/"$job"/*.json "$tmp/data/jobs/$job/" 2>/dev/null || true
      if [ -d "data/jobs/$job/stills" ]; then cp -r "data/jobs/$job/stills" "$tmp/data/jobs/$job/"; fi
    fi
  done
  git -C "$tmp" init -q -b state
  git -C "$tmp" add -A
  git -C "$tmp" -c user.name="github-actions[bot]" \
    -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit -qm "pipeline state $(date -u +%FT%TZ)"
  git -C "$tmp" push -qf "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" state
  echo "saved state branch"
  exit 0
fi
echo "usage: $0 pull|push" >&2; exit 2
