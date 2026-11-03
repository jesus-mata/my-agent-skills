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
links_file_to() { [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ] && [ -f "$1" ]; }

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
mentions_templates() { grep -v '^clone:' "$1" | grep -q -e template -e coder.md; }
expect "status says nothing about templates without hc" no mentions_templates "$FAKE/status.txt"

echo "== hc template lib =="
expect "no home is created for an absent hc"      no  test -d "$FAKE/.config/herdr-core"
mkdir -p "$FAKE/.config/herdr-core"
run install >/dev/null
expect "links lib beside the templates"           yes links_to "$FAKE/.config/herdr-core/templates/lib" "$CLONE/templates/lib"
run install >/dev/null
expect "second install keeps the lib link"        yes links_to "$FAKE/.config/herdr-core/templates/lib" "$CLONE/templates/lib"
run uninstall e2e >/dev/null
expect "a narrowed uninstall keeps the lib link"  yes links_to "$FAKE/.config/herdr-core/templates/lib" "$CLONE/templates/lib"
run install >/dev/null
rm "$FAKE/.config/herdr-core/templates/lib"
mkdir "$FAKE/.config/herdr-core/templates/lib"
expect "a real lib folder fails the install"      no  run install
expect "a real lib folder is left in place"       yes test -d "$FAKE/.config/herdr-core/templates/lib"
rmdir "$FAKE/.config/herdr-core/templates/lib"
run install >/dev/null

echo "== hc templates =="
HC_TEMPLATES="$FAKE/.config/herdr-core/templates"
every_template_linked() {
  for _f in "$CLONE"/templates/*.md; do
    links_file_to "$HC_TEMPLATES/$(basename "$_f")" "$_f" || return 1
  done
}
no_template_linked() {
  for _f in "$CLONE"/templates/*.md; do
    _t="$HC_TEMPLATES/$(basename "$_f")"
    [ ! -e "$_t" ] && [ ! -L "$_t" ] || return 1
  done
}
rm -rf "$FAKE/.config/herdr-core"
run install >/dev/null
expect "no herdr-core folder is created for the templates" no test -e "$FAKE/.config/herdr-core"
mkdir -p "$FAKE/.config/herdr-core"
run install --dry-run > "$FAKE/dry.txt" 2>&1
expect "install --dry-run names the templates"     yes grep -q "would link coder.md" "$FAKE/dry.txt"
expect "install --dry-run links no template"       yes no_template_linked
run install >/dev/null
expect "install links every template"              yes every_template_linked
ls -li "$HC_TEMPLATES" > "$FAKE/before.txt"
run install >/dev/null
ls -li "$HC_TEMPLATES" > "$FAKE/after.txt"
expect "second install keeps the template links"   yes every_template_linked
expect "second install changes nothing"            yes cmp -s "$FAKE/before.txt" "$FAKE/after.txt"
rm "$HC_TEMPLATES/coder.md"
echo "my own coder" > "$HC_TEMPLATES/coder.md"
rm "$HC_TEMPLATES/reviewer.md"
mkdir -p "$FAKE/elsewhere"
echo "another clone's reviewer" > "$FAKE/elsewhere/reviewer.md"
ln -s "$FAKE/elsewhere/reviewer.md" "$HC_TEMPLATES/reviewer.md"
if run install > "$FAKE/foreign.txt" 2>&1; then _rc=0; else _rc=1; fi
expect "a foreign template does not fail the install" yes test "$_rc" -eq 0
expect "a real template file is left in place"     yes grep -q "my own coder" "$HC_TEMPLATES/coder.md"
expect "a real template file is reported"          yes grep -q "templates/coder.md is not a link" "$FAKE/foreign.txt"
expect "a template link elsewhere is left alone"   yes links_file_to "$HC_TEMPLATES/reviewer.md" "$FAKE/elsewhere/reviewer.md"
expect "a template link elsewhere is reported"     yes grep -q "templates/reviewer.md is not a link" "$FAKE/foreign.txt"
rm "$HC_TEMPLATES/coder.md" "$HC_TEMPLATES/reviewer.md"
run install >/dev/null
# A template added upstream goes into a throwaway copy of the clone, never the real one. The
# copy has no .git, so update skips the pull; it gets its own $HOME and herdr-core.
mkdir -p "$FAKE/copy" "$FAKE/copy-home/.claude" "$FAKE/copy-home/.config/herdr-core"
COPY=$(CDPATH='' cd -- "$FAKE/copy" && pwd -P)
cp -R "$CLONE/bin" "$CLONE/skills" "$CLONE/templates" "$COPY/"
echo "a template added upstream" > "$COPY/templates/added.md"
run_copy() { HOME="$FAKE/copy-home" XDG_CONFIG_HOME="$FAKE/copy-home/.config" NO_COLOR=1 "$COPY/bin/agent-skills" "$@"; }
COPY_TEMPLATES="$FAKE/copy-home/.config/herdr-core/templates"
mkdir -p "$COPY_TEMPLATES"
# a template removed upstream, and a dangling link that belongs to someone else
ln -s "$COPY/templates/removed.md" "$COPY_TEMPLATES/removed.md"
ln -s "$FAKE/elsewhere/vanished.md" "$COPY_TEMPLATES/vanished.md"
if run_copy update --dry-run > "$FAKE/dry-update.txt" 2>&1; then _rc=0; else _rc=1; fi
expect "update --dry-run succeeds"                 yes test "$_rc" -eq 0
expect "update --dry-run names the template to prune" yes grep -q "would unlink removed.md" "$FAKE/dry-update.txt"
expect "update --dry-run prunes no template link"  yes test -L "$COPY_TEMPLATES/removed.md"
if run_copy update > "$FAKE/update.txt" 2>&1; then _rc=0; else _rc=1; fi
expect "update succeeds"                           yes test "$_rc" -eq 0
expect "update links a template added to the clone" yes links_file_to "$COPY_TEMPLATES/added.md" "$COPY/templates/added.md"
expect "update prunes a template whose source is gone" no test -L "$COPY_TEMPLATES/removed.md"
expect "update leaves a dangling link elsewhere alone" yes test -L "$COPY_TEMPLATES/vanished.md"
expect "update reports a dangling link elsewhere"  yes grep -q "vanished.md.*dangling" "$FAKE/update.txt"
ln -s "$COPY/templates/removed.md" "$COPY_TEMPLATES/removed.md"
run_copy prune --target claude >/dev/null 2>&1
expect "a narrowed prune keeps the template links" yes test -L "$COPY_TEMPLATES/removed.md"
rm "$HC_TEMPLATES/coder.md"
rm "$HC_TEMPLATES/reviewer.md"
echo "my own reviewer" > "$HC_TEMPLATES/reviewer.md"
run status > "$FAKE/status.txt" 2>&1
expect "status reports a linked template"          yes grep -q "e2e-tester.md linked" "$FAKE/status.txt"
expect "status reports a missing template"         yes grep -q "coder.md is not linked" "$FAKE/status.txt"
expect "a missing template names its fix"          yes grep -q "coder.md is not linked.*(run: update)" "$FAKE/status.txt"
expect "status reports a foreign template"         yes grep -q "templates/reviewer.md is not a link to this clone" "$FAKE/status.txt"
each_template_once() {
  for _f in "$CLONE"/templates/*.md; do
    [ "$(grep -cE "^  . (.*/)?$(basename "$_f") " "$1")" -eq 1 ] || return 1
  done
}
expect "status lists every template once"          yes each_template_once "$FAKE/status.txt"
expect "status prints the hc templates heading once" yes test "$(grep -c '^hc templates' "$FAKE/status.txt")" -eq 1
rm "$HC_TEMPLATES/reviewer.md"
run install >/dev/null

echo "== uninstall touches only our links =="
mkdir -p "$FAKE/.claude/skills/someone-elses"
echo "my own template" > "$HC_TEMPLATES/mine.md"
ln -s "$FAKE/elsewhere/reviewer.md" "$HC_TEMPLATES/theirs.md"
run uninstall e2e >/dev/null
expect "a narrowed uninstall keeps the template links" yes every_template_linked
run uninstall --target claude >/dev/null
expect "uninstall --target keeps the template links" yes every_template_linked
run install >/dev/null
run uninstall --dry-run >/dev/null
expect "uninstall --dry-run removes no template"  yes every_template_linked
expect "uninstall --dry-run keeps the lib link"   yes links_to "$HC_TEMPLATES/lib" "$CLONE/templates/lib"
run uninstall >/dev/null
expect "uninstall removes every template link"    yes no_template_linked
expect "uninstall leaves a real template file"    yes grep -q "my own template" "$HC_TEMPLATES/mine.md"
expect "uninstall leaves a template link elsewhere" yes links_file_to "$HC_TEMPLATES/theirs.md" "$FAKE/elsewhere/reviewer.md"
expect "uninstall removes the lib link"           no  test -L "$FAKE/.config/herdr-core/templates/lib"
expect "uninstall removes our links"              no  test -L "$FAKE/.claude/skills/e2e"
expect "uninstall leaves foreign content alone"   yes test -d "$FAKE/.claude/skills/someone-elses"

echo ""
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
