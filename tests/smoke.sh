#!/bin/sh
# Smoke test: link into a throwaway $HOME and assert the links are real.
# The failure this guards against is "the installer bricks a device", so it exercises the
# destructive paths — shadows, foreign links, dangling links, uninstall — not just the happy one.
set -eu

CLONE=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
FAKE=$(mktemp -d)
trap 'rm -rf "$FAKE"' EXIT INT TERM

pass=0
fail=0

report() {
  if [ "$2" = ok ]; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$1"
  else
    fail=$((fail + 1)); printf '  FAIL %s\n' "$1"
  fi
}

# expect <description> <yes|no> <command...>
expect() {
  _desc=$1; _want=$2; shift 2
  if "$@" >/dev/null 2>&1; then _got=yes; else _got=no; fi
  if [ "$_got" = "$_want" ]; then report "$_desc" ok; else report "$_desc" no; fi
}

links_to() { [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ] && [ -d "$1" ]; }

run() { HOME="$FAKE" XDG_CONFIG_HOME="$FAKE/.config" NO_COLOR=1 "$CLONE/bin/agent-skills" "$@"; }

# two agents installed, one deliberately absent
mkdir -p "$FAKE/.claude" "$FAKE/.codex"
AGENT_SKILLS_BACKUP_DIR="$FAKE/backups"
export AGENT_SKILLS_BACKUP_DIR

echo "== install =="
run install >/dev/null
expect "links into a detected target"            yes links_to "$FAKE/.claude/skills/e2e" "$CLONE/skills/e2e"
expect "links into every detected target"        yes links_to "$FAKE/.codex/skills/refine-ticket" "$CLONE/skills/refine-ticket"
expect "a linked skill resolves to real content" yes test -f "$FAKE/.claude/skills/e2e/SKILL.md"
expect "no home is created for an absent agent"  no  test -d "$FAKE/.gemini"

echo "== install is idempotent =="
run install >/dev/null
expect "second install leaves links intact" yes links_to "$FAKE/.claude/skills/e2e" "$CLONE/skills/e2e"

echo "== a shadowing directory is never destroyed =="
rm "$FAKE/.claude/skills/e2e"
mkdir -p "$FAKE/.claude/skills/e2e"
echo "older copy" > "$FAKE/.claude/skills/e2e/SKILL.md"
expect "shadow makes install exit non-zero"      no  run install e2e
expect "shadow is left in place without --force" yes test -f "$FAKE/.claude/skills/e2e/SKILL.md"
run install e2e --force >/dev/null
expect "--force replaces the shadow"             yes links_to "$FAKE/.claude/skills/e2e" "$CLONE/skills/e2e"
expect "the shadow was backed up, not deleted"   yes test -f "$FAKE/backups/$(ls "$FAKE/backups")/claude/e2e/SKILL.md"

echo "== a foreign link is not ours to delete =="
mkdir -p "$FAKE/elsewhere/e2e"
rm "$FAKE/.codex/skills/e2e"
ln -s "$FAKE/elsewhere/e2e" "$FAKE/.codex/skills/e2e"
expect "foreign link makes install exit non-zero" no  run install e2e --target codex
expect "foreign link survives without --force"    yes links_to "$FAKE/.codex/skills/e2e" "$FAKE/elsewhere/e2e"
run install e2e --target codex --force >/dev/null
expect "--force takes over a foreign link"        yes links_to "$FAKE/.codex/skills/e2e" "$CLONE/skills/e2e"

echo "== prune =="
ln -s "$CLONE/skills/deleted-upstream" "$FAKE/.claude/skills/deleted-upstream"
run prune >/dev/null
expect "a dangling link into the clone is pruned" no test -L "$FAKE/.claude/skills/deleted-upstream"

echo "== unknown agent via --target =="
run install --target "$FAKE/other-agent/skills" >/dev/null
expect "--target <path> links an unknown agent" yes links_to "$FAKE/other-agent/skills/e2e" "$CLONE/skills/e2e"

echo "== adopt --dry-run changes nothing =="
mkdir -p "$FAKE/.claude/skills/adoptable"
printf -- '---\nname: adoptable\ndescription: "A skill waiting to be adopted into the clone"\n---\n' > "$FAKE/.claude/skills/adoptable/SKILL.md"
expect "adopt --dry-run succeeds"                 yes run adopt adoptable --target claude --dry-run
expect "adopt --dry-run leaves the skill in place" yes test -f "$FAKE/.claude/skills/adoptable/SKILL.md"
expect "adopt --dry-run adds nothing to the clone" no  test -e "$CLONE/skills/adoptable"
rm -rf "$FAKE/.claude/skills/adoptable"

echo "== status =="
run status > "$FAKE/status.txt" 2>&1
expect "status reports linked skills" yes grep -q linked "$FAKE/status.txt"

echo "== uninstall touches only our links =="
mkdir -p "$FAKE/.claude/skills/someone-elses"
run uninstall >/dev/null
expect "uninstall removes our links"              no  test -L "$FAKE/.claude/skills/e2e"
expect "uninstall leaves foreign content alone"   yes test -d "$FAKE/.claude/skills/someone-elses"

echo ""
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
