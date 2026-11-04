#!/bin/sh
# Turns a fixture into an eval sandbox: a git repo whose `origin` is a local bare repo, so a
# spike can branch, commit and push without touching any real remote.
#   setup-fixture.sh <fixture-name> <dest-dir>
# Creates <dest-dir>/origin.git and <dest-dir>/repo, a clone on main.
set -eu
[ $# -eq 2 ] || { echo "usage: $0 <fixture-name> <dest-dir>" >&2; exit 2; }
src="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)/fixtures/$1"
[ -d "$src" ] || { echo "setup-fixture: no fixture named $1" >&2; exit 1; }
[ ! -e "$2" ] || { echo "setup-fixture: $2 already exists" >&2; exit 1; }
mkdir -p "$2"
dest="$(CDPATH='' cd -- "$2" && pwd -P)"
seed="$dest/.seed"
cp -R "$src" "$seed"
git -C "$seed" init -q -b main
git -C "$seed" add -A
git -C "$seed" -c user.email=fixture@example.com -c user.name=fixture commit -qm "$1 fixture"
git clone -q --bare "$seed" "$dest/origin.git"
git clone -q "$dest/origin.git" "$dest/repo"
rm -rf "$seed"
echo "$dest/repo"
