#!/bin/sh
# Checks the Claude flags and labels hc-claude produces, with stub hc, jq failures and claude.
set -eu

CLONE=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
STUBS=$(mktemp -d)
trap 'rm -rf "$STUBS"' EXIT INT TERM

cat > "$STUBS/claude" <<'EOF'
#!/bin/sh
printf '[%s]' "$@"
EOF
cat > "$STUBS/hc" <<'EOF'
#!/bin/sh
case $1 in
  get)
    [ -z "${STUB_GET_FAILS:-}" ] || exit 1
    printf '{"labels":%s}\n' "$STUB_LABELS"
    ;;
  label)
    [ -z "${STUB_LABEL_FAILS:-}" ] || exit 1
    shift 2
    printf '%s' "$*" > "$STUB_RECORDED"
    ;;
esac
EOF
chmod +x "$STUBS/claude" "$STUBS/hc"

PATH="$STUBS:$PATH"
STUB_RECORDED="$STUBS/recorded"
export PATH STUB_RECORDED

pass=0
fail=0

report() {
  if [ "$2" = ok ]; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$1"
  else
    fail=$((fail + 1)); printf '  FAIL %s\n' "$1"
  fi
}

# flags <description> <labels json> <expected claude args> <expected labels>
flags() {
  rm -f "$STUB_RECORDED"
  _got=$(HC_TERMINAL_ID=t1 STUB_LABELS=$2 "$CLONE/templates/lib/hc-claude" --keep "" 2>&1) || true
  _recorded=$(cat "$STUB_RECORDED" 2>/dev/null || true)
  if [ "$_got" = "$3" ] && [ "$_recorded" = "$4" ]; then
    report "$1" ok
  else
    report "$1: got $_got, labels $_recorded" no
  fi
}

# stops <description> <VAR=value...>
stops() {
  _desc=$1; shift
  if _got=$(env HC_TERMINAL_ID=t1 'STUB_LABELS={}' "$@" "$CLONE/templates/lib/hc-claude" 2>&1); then
    report "$_desc: started: $_got" no
  else
    case $_got in
      *hc-claude:*) report "$_desc" ok ;;
      *) report "$_desc: $_got" no ;;
    esac
  fi
}

echo "== defaults =="
flags "no labels: opus at medium" '{}' \
  '[--model][opus][--effort][medium][--keep][]' 'model=opus effort=medium'
flags "opus alias: medium" '{"model":"opus"}' \
  '[--model][opus][--effort][medium][--keep][]' 'model=opus effort=medium'
flags "sonnet alias: high" '{"model":"sonnet"}' \
  '[--model][sonnet][--effort][high][--keep][]' 'model=sonnet effort=high'
flags "full opus id: medium" '{"model":"claude-opus-5-5"}' \
  '[--model][claude-opus-5-5][--effort][medium][--keep][]' 'model=claude-opus-5-5 effort=medium'
flags "full sonnet id: high" '{"model":"claude-sonnet-5-5"}' \
  '[--model][claude-sonnet-5-5][--effort][high][--keep][]' 'model=claude-sonnet-5-5 effort=high'
flags "other model: no effort flag" '{"model":"haiku"}' \
  '[--model][haiku][--keep][]' 'model=haiku'

echo "== explicit effort =="
flags "effort label wins over the default" '{"model":"sonnet","effort":"low"}' \
  '[--model][sonnet][--effort][low][--keep][]' 'model=sonnet effort=low'
flags "effort applies to any model" '{"model":"haiku","effort":"low"}' \
  '[--model][haiku][--effort][low][--keep][]' 'model=haiku effort=low'
flags "effort alone keeps the default model" '{"effort":"max"}' \
  '[--model][opus][--effort][max][--keep][]' 'model=opus effort=max'
flags "bracketed model survives" '{"model":"opus[1m]","effort":"low"}' \
  '[--model][opus[1m]][--effort][low][--keep][]' 'model=opus[1m] effort=low'

echo "== outside hc =="
got=$(env -u HC_TERMINAL_ID "$CLONE/templates/lib/hc-claude" --keep)
if [ "$got" = '[--model][opus][--effort][medium][--keep]' ]; then
  report "no terminal: defaults" ok
else
  report "no terminal: got $got" no
fi

echo "== unreadable labels stop the start =="
stops "hc get fails" STUB_GET_FAILS=1
stops "labels are not JSON" 'STUB_LABELS=not json'
stops "hc label fails" STUB_LABEL_FAILS=1
stops "jq is missing" "PATH=$STUBS"
stops "unknown effort" 'STUB_LABELS={"effort":"hgih"}'

echo ""
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
