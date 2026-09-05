#!/usr/bin/env bash
# Greppable small-screen rules from DESIGN.md §1.11. Each rule is a ratchet:
# the count may go down, never up, against scripts/lint-mobile-baseline.json.
# Rerun with --update after deliberately removing violations to lower the bar.
set -eu
cd "$(dirname "$0")/.."
BASELINE=scripts/lint-mobile-baseline.json
UPDATE=${1:-}

count_matches() { # $1 = rule name; prints count of matching lines
  case "$1" in
    # Layout decisions from media queries outside the viewport composable.
    # Popover geometry (innerWidth arithmetic) is not a layout decision and
    # is not matched here.
    media-query-outside-useViewport)
      grep -rnE "matchMedia\([^)]*(min-width|max-width|pointer)" src \
        --include='*.vue' --include='*.js' --include='*.ts' \
        | grep -v "src/composables/useViewport.ts" | wc -l || true ;;
    # Fixed widths >= 360px with no breakpoint prefix: guaranteed overflow on
    # a 390px phone. Prefix with md:/lg: or use max-w-full / percentages.
    fixed-width-no-breakpoint)
      grep -rnoE "(^|[\" '])(min-w|w)-\[[0-9]{3,}px\]" src --include='*.vue' \
        | awk -F'[][]' '{n=$2; sub("px","",n); if (n+0>=360) print}' | wc -l || true ;;
    # Hover-revealed controls with no non-hover path. Approximation: every
    # group-hover:opacity-100 is suspect until it also carries a coarse
    # pointer fallback ([data-pointer=coarse]_&:opacity-100 or a menu twin).
    hover-only-control)
      grep -rn "group-hover:opacity-100" src --include='*.vue' \
        | grep -v "data-pointer" | wc -l || true ;;
    # Window width read for a layout decision (comparison), not geometry.
    innerWidth-layout-decision)
      grep -rnE "innerWidth\s*[<>]=?\s*[0-9]{3,}" src \
        --include='*.vue' --include='*.js' --include='*.ts' | wc -l || true ;;
  esac
}

RULES="media-query-outside-useViewport fixed-width-no-breakpoint hover-only-control innerWidth-layout-decision"

if [[ "$UPDATE" == "--update" ]]; then
  {
    echo "{"
    first=1
    for r in $RULES; do
      c=$(count_matches "$r")
      [[ $first -eq 1 ]] || echo ","
      first=0
      printf '  "%s": %s' "$r" "$c"
    done
    echo
    echo "}"
  } > "$BASELINE"
  echo "baseline written to $BASELINE"; cat "$BASELINE"; exit 0
fi

fail=0
for r in $RULES; do
  c=$(count_matches "$r")
  b=$(python3 -c "import json,sys; print(json.load(open('$BASELINE')).get('$r', 0))")
  if (( c > b )); then
    echo "FAIL $r: $c violations (baseline $b). New small-screen violation — see DESIGN.md §1.11."
    fail=1
  else
    echo "ok   $r: $c (baseline $b)"
  fi
done
exit $fail
