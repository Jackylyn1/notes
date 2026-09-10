#!/usr/bin/env bash
# Pre-publish gate. Exits non-zero on any failure, so it is a gate rather than a
# report somebody has to read. Run it before every push.
#
#   ./check.sh
#
# The two anchor checks are the load-bearing ones: a duplicate anchor makes a
# published deep link ambiguous, and an auto-deduplicated "_1" anchor is
# unstable, so a post linking to it breaks on the next edit.

set -uo pipefail
cd "$(dirname "$0")"

PY=./.venv/bin/python
RUFF=./.venv/bin/ruff
MYPY=./.venv/bin/mypy
fail=0

chk() { printf '%-46s' "$1"; }
ok() { echo "PASS${1:+ ($1)}"; }
no() {
  echo "FAIL${1:+ ($1)}"
  fail=1
}

# Rebuild first: every check below inspects the built output.
$PY build.py >/dev/null || {
  echo "build failed"
  exit 1
}

chk "anchors: no duplicates"
n=$(grep -oE 'id="[^"]+"' docs/index.html | sort | uniq -d | wc -l)
[ "$n" = 0 ] && ok || no "$n duplicates"

chk "anchors: no unstable _N suffix"
n=$(grep -oE 'id="[^"]*_[0-9]+"' docs/index.html | wc -l)
[ "$n" = 0 ] && ok || no "$n unstable"

chk "anchors: h3 count matches source"
a=$(grep -c '^### ' content/learnings.md)
b=$(grep -oc '<h3 id=' docs/index.html)
[ "$a" = "$b" ] && ok "$a" || no "$a vs $b"

chk "tables: all converted"
a=$(grep -cE '^\|[ :|-]+\|$' content/learnings.md)
b=$(grep -oc '<table>' docs/index.html)
[ "$a" = "$b" ] && ok "$a" || no "$a vs $b"

chk "no raw markdown leaked"
n=$(grep -cE '^\|---' docs/index.html)
[ "$n" = 0 ] && ok || no

# No employer, client or internal-system names. This property is not
# self-maintaining; it is re-checked on every publish.
chk "anonymisation guard"
n=$(grep -niE 'gastro|gpos|riverty|wpt|naruto|EKIP|kassensich|dsfinv|filament|serena|gitlab|RAGTask|career-kb|profile\.json|Company [A-Z]' \
  docs/index.html content/learnings.md | wc -l)
[ "$n" = 0 ] && ok || no "$n hits"

chk "every token in base :root"
n=$(grep -c -- '--bg:' assets/site.css)
[ "$n" = 1 ] && ok || no "declared $n times"

chk "no light-theme override"
n=$(grep -c 'prefers-color-scheme' assets/site.css)
[ "$n" = 0 ] && ok || no

chk "print block present"
grep -q '@media print' assets/site.css && ok || no

chk "scroll-margin-top for deep links"
grep -q 'scroll-margin-top' assets/site.css && ok || no

chk "og:image + canonical present"
grep -q 'og:image' docs/index.html && grep -q 'rel="canonical"' docs/index.html && ok || no

chk "og image is 1200x630"
if command -v identify >/dev/null 2>&1; then
  d=$(identify -format '%wx%h' docs/assets/og.png 2>/dev/null)
  [ "$d" = "1200x630" ] && ok "$d" || no "$d"
else
  echo "SKIP (no imagemagick)"
fi

chk "card source not published"
[ ! -f docs/assets/og-card.html ] && ok || no "og-card.html is served"

chk "ruff"
$RUFF check -q build.py && ok || no

chk "ruff format"
$RUFF format --check -q build.py >/dev/null 2>&1 && ok || no

chk "mypy"
$MYPY --ignore-missing-imports build.py >/dev/null 2>&1 && ok || no

echo
if [ "$fail" = 0 ]; then
  echo "ALL CHECKS PASS — safe to publish"
else
  echo "FAILURES — do not publish"
fi
exit "$fail"
