#!/usr/bin/env bash
# Smoke-test a running literenare API with curl.
#
#   tests/curl/run.sh                     # all checks against http://localhost:8080
#   tests/curl/run.sh match               # only checks whose name contains "match"
#   tests/curl/run.sh -v systemone        # also print the curl command and full response
#   BASE_URL=http://host:8080 API_KEY=secret tests/curl/run.sh
#
# Needs bash + curl. With jq installed, each check prints a short summary of the response.
# Exit code = number of failed checks. Works with macOS's bash 3.2.

set -u
BASE_URL="${BASE_URL:-http://localhost:8080}"
API_KEY="${API_KEY:-}"
REQ="$(cd "$(dirname "$0")" && pwd)/requests"

VERBOSE=0
FILTER=""
for arg in "$@"; do
  case "$arg" in
    -v|--verbose) VERBOSE=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) FILTER="$arg" ;;
  esac
done

if [ -t 1 ]; then G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; D=$'\e[2m'; B=$'\e[1m'; N=$'\e[0m'; JQ_COLOR=-C
else G=""; R=""; Y=""; D=""; B=""; N=""; JQ_COLOR=-M; fi
HAVE_JQ=0; command -v jq >/dev/null 2>&1 && HAVE_JQ=1

PASS=0; FAIL=0; SKIP=0; SAW_502=0; PENDING_SECTION=""
OUT="$(mktemp)"; ERR="$(mktemp)"; trap 'rm -f "$OUT" "$ERR"' EXIT

# check NAME METHOD PATH EXPECTED_STATUS [BODY] [JQ_SUMMARY] [KEY_OVERRIDE]
#   BODY: inline JSON, or @file (curl reads it), or "" for none.
check() {
  local name="$1" method="$2" path="$3" expect="$4" body="${5:-}" summary="${6:-.}"
  local key="${7-$API_KEY}"
  if [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]]; then return; fi
  flush_section

  local args=(-sS -X "$method" -o "$OUT" -w '%{http_code} %{time_total}'
              -H 'Accept: application/json')
  [ -n "$key" ] && args+=(-H "X-API-Key: $key")
  [ -n "$body" ] && args+=(-H 'Content-Type: application/json' --data-binary "$body")

  local result status secs
  : > "$OUT"
  result="$(curl "${args[@]}" "$BASE_URL$path" 2>"$ERR")"
  status="${result%% *}"; secs="${result##* }"
  [ "$status" = "000" ] && status="ERR"
  [ "$status" = "502" ] && SAW_502=1

  if [ "$status" = "$expect" ]; then
    PASS=$((PASS + 1))
    printf '%s✔%s %-26s %s%-6s %s%s → %s %s(%ss)%s\n' "$G" "$N" "$name" "$D" "$method" "$path" "$N" "$status" "$D" "$secs" "$N"
  else
    FAIL=$((FAIL + 1))
    printf '%s✘ %-26s%s %-6s %s → %s%s%s (expected %s)\n' "$R" "$name" "$N" "$method" "$path" "$R" "$status" "$N" "$expect"
    [ "$status" = "ERR" ] && printf '    %s%s%s\n' "$D" "$(cat "$ERR")" "$N"
  fi

  if [ "$VERBOSE" = 1 ]; then
    local shown_body="$body"
    printf '    %s$ curl -X %s %s%s' "$D" "$method" "$BASE_URL" "$path"
    [ -n "$key" ] && printf " -H 'X-API-Key: …'"
    [ -n "$shown_body" ] && printf " -H 'Content-Type: application/json' -d '%s'" "$shown_body"
    printf '%s\n' "$N"
  fi

  [ -s "$OUT" ] || return
  if [ "$HAVE_JQ" = 1 ] && jq -e . "$OUT" >/dev/null 2>&1; then
    if [ "$VERBOSE" = 1 ] || [ "$status" != "$expect" ]; then
      jq "$JQ_COLOR" . "$OUT" | sed 's/^/    /'          # full, pretty
    else
      jq "$JQ_COLOR" -c "$summary" "$OUT" 2>/dev/null | sed 's/^/    /'   # one-line summary
    fi
  elif [ "$VERBOSE" = 1 ] || [ "$status" != "$expect" ]; then
    sed 's/^/    /' "$OUT"; echo
  fi
}

skip() {
  if [ -n "$FILTER" ] && [[ "$1" != *"$FILTER"* ]]; then return; fi
  flush_section
  SKIP=$((SKIP + 1)); printf '%s- %-26s skipped: %s%s\n' "$Y" "$1" "$2" "$N"
}

# Section headers are printed lazily, so a filtered run shows no empty sections.
section() { PENDING_SECTION="$1"; }
flush_section() {
  [ -n "$PENDING_SECTION" ] && printf '\n%s%s%s\n' "$B" "$PENDING_SECTION" "$N"
  PENDING_SECTION=""
}

printf '%sliterenare curl checks%s → %s%s\n' "$B" "$N" "$BASE_URL" "$( [ "$HAVE_JQ" = 0 ] && echo "  (install jq for summaries)")"

# --- service ---------------------------------------------------------------------
section "Service"
check health                GET  /health                   200 "" '.status' ""
if [ -n "$API_KEY" ]; then
  check auth_wrong_key      GET  /v1/pipelines             401 "" '.detail' "wrong-key"
  check auth_missing_key    GET  /v1/pipelines             401 "" '.detail' ""
else
  skip auth_wrong_key "API_KEY not set (auth disabled?)"
fi

# --- introspection -----------------------------------------------------------------
section "Introspection"
check list_grants           GET  /v1/grants                200 "" 'map({id, title})'
check list_pipelines        GET  /v1/pipelines             200 "" 'map_values(map(.step))'
check list_steps            GET  /v1/steps                 200 "" 'map_values(.params | keys)'

# --- grant matching ----------------------------------------------------------------
MATCH_SUMMARY='{rank_by, considered, matches: [.matches[] | {grant_id, probability, gated_by}], trace}'
section "Grant matching"
check match_profile         POST /v1/grants/match          200 "@$REQ/match_profile.json"       "$MATCH_SUMMARY"
check match_structured      POST /v1/grants/match          200 "@$REQ/match_structured.json"    "$MATCH_SUMMARY"
check match_inline_grants   POST /v1/grants/match          200 "@$REQ/match_inline_grants.json" "$MATCH_SUMMARY"
check match_unknown_grant   POST /v1/grants/match          404 '{"profile": "x", "grant_ids": ["does-not-exist"]}' '.detail'
check match_bad_pipeline    POST /v1/grants/match          404 '{"profile": "x", "pipeline": "nope"}' '.detail'
check match_missing_profile POST /v1/grants/match          422 '{"top_k": 3}' '[.detail[].msg]'

# --- application alignment ---------------------------------------------------------
section "Application alignment"
check align                 POST /v1/applications/align    200 "@$REQ/align.json" \
  '.alignment | {grant_id, probability, gated_by, answers: (.answers | map_values(.noul // .score // .choice))}'
check align_missing_grant   POST /v1/applications/align    422 "@$REQ/align_missing_grant.json" '.detail'

# --- raw systemone -------------------------------------------------------------------
section "SystemOne passthrough"
check systemone_ticket      POST /v1/systemone             200 "@$REQ/systemone_ticket.json" \
  '{model, answers: (.answers | map_values(del(.legend)))}'
check systemone_invalid     POST /v1/systemone             422 "@$REQ/systemone_invalid.json" '.detail'

# --- generic pipelines -------------------------------------------------------------
section "Pipelines"
check pipeline_run          POST /v1/pipelines/grant_match/run 200 "@$REQ/pipeline_run.json" "$MATCH_SUMMARY"
check pipeline_unknown      POST /v1/pipelines/nope/run    404 '{"inputs": {}}' '.detail'

# --- summary -------------------------------------------------------------------------
printf '\n%s%d passed%s, %s%d failed%s, %d skipped\n' "$G" "$PASS" "$N" \
  "$( [ "$FAIL" -gt 0 ] && echo "$R" )" "$FAIL" "$N" "$SKIP"
if [ "$SAW_502" = 1 ]; then
  printf '%sA 502 on match/align/systemone means the API is up but the JeV backend is not reachable (check JEV_BASE_URL).%s\n' "$D" "$N"
fi
exit "$FAIL"
