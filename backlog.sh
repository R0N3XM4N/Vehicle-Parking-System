#!/usr/bin/env bash
# Creates labels, Sprint milestones, a GitHub Project and the product backlog for
# Vehicle-Parking-System, built from the requirement IDs in the SRS (PVT-F, PVT-NF, PRJ-SR).
#
#   DRY_RUN=1 bash backlog.sh                       # preview only, creates nothing
#   M1=<user> M2=<user> M3=<user> M4=<user> bash backlog.sh
#
# Member roles: M1 Backend/DB/Auth/Security, M2 Parking Management, M3 Frontend/UI,
#               M4 Testing/GitHub/Documentation.
# Assignees must be collaborators on the repo; if assigning fails the issue is still
# created (unassigned). Safe to re-run: issues whose title already exists are skipped.
set -uo pipefail

REPO="${REPO:-R0N3XM4N/Vehicle-Parking-System}"
OWNER="${REPO%%/*}"
DRY_RUN="${DRY_RUN:-0}"
CREATE_PROJECT="${CREATE_PROJECT:-1}"
PROJECT_NUMBER="${PROJECT_NUMBER:-}"

if [ "$DRY_RUN" != 1 ]; then
  ME="$(gh api user --jq .login 2>/dev/null || true)"
fi
M1="${M1:-}"; M2="${M2:-${ME:-}}"; M3="${M3:-}"; M4="${M4:-}"

run() { if [ "$DRY_RUN" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }

echo "== Labels =="
mk_label() { run gh label create "$1" --color "$2" --description "$3" --repo "$REPO" --force >/dev/null 2>&1 || echo "  warn: label '$1' not created"; }
mk_label story 0052cc "User story / backlog item"
mk_label sprint-1 1d76db "Sprint 1 (19-23 Oct)"
mk_label sprint-2 5319e7 "Sprint 2 (26-30 Oct)"
mk_label backend 0e8a16 "Backend, database, auth, security"
mk_label parking fbca04 "Parking management"
mk_label frontend d93f0b "Frontend / UI"
mk_label testing-docs c5def5 "Testing, CI, documentation"
for p in 2 3 5; do mk_label "sp:$p" ededed "Story points: $p"; done

echo "== Milestones =="
run gh api "repos/$REPO/milestones" -f title="Sprint 1" -f description="Auth, slots, availability, entry/exit, base UI, CI" -f due_on="2026-10-23T23:59:59Z" >/dev/null 2>&1 || echo "  (Sprint 1 exists or could not be created)"
run gh api "repos/$REPO/milestones" -f title="Sprint 2" -f description="Fees, payments, reservations, admin, reports, security, testing, docs" -f due_on="2026-10-30T23:59:59Z" >/dev/null 2>&1 || echo "  (Sprint 2 exists or could not be created)"

echo "== Project =="
if [ "$DRY_RUN" = 1 ]; then
  echo "  [dry-run] would create project 'Vehicle Parking System Backlog' and link it to $REPO"
  PROJECT_NUMBER=""
elif [ -z "$PROJECT_NUMBER" ] && [ "$CREATE_PROJECT" = 1 ]; then
  PROJECT_NUMBER="$(gh project create --owner "$OWNER" --title "Vehicle Parking System Backlog" --format json --jq .number 2>/dev/null || true)"
  if [ -n "$PROJECT_NUMBER" ]; then
    gh project link "$PROJECT_NUMBER" --owner "$OWNER" --repo "$REPO" >/dev/null 2>&1 || echo "  warn: could not link project to repo"
    echo "  created project #$PROJECT_NUMBER"
  else
    echo "  warn: project not created (token needs the 'project' scope: gh auth refresh -s project)"
  fi
fi

echo "== Issues =="
existing=""
[ "$DRY_RUN" = 1 ] || existing="$(gh issue list --repo "$REPO" --state all --limit 500 --json title --jq '.[].title' 2>/dev/null || true)"
created=0; skipped=0; failed=0

# sprint|points|label|member|SRS id|title|acceptance criteria|test case
while IFS='|' read -r -u 3 sprint sp label member srs title ac tc; do
  [ -z "$sprint" ] && continue
  case "$srs" in PVT*|PRJ*) full="[$srs] $title" ;; *) full="$title" ;; esac

  if printf '%s\n' "$existing" | grep -Fxq -- "$full"; then
    echo "  skip (exists): $full"; skipped=$((skipped+1)); continue
  fi

  var="M$member"; who="${!var}"
  body="$(printf '**SRS reference:** %s\n**Acceptance criteria:** %s\n**Test case:** %s\n**Story points:** %s | **Sprint:** %s\n\n**Definition of done:** assigned member raises a PR that closes this issue, the repo owner reviews and merges it, and the matching test case passes.' "$srs" "$ac" "$tc" "$sp" "$sprint")"

  if [ "$DRY_RUN" = 1 ]; then
    echo "  [dry-run] S$sprint sp=$sp $label M$member -> $full"; created=$((created+1)); continue
  fi

  args=(issue create --repo "$REPO" --title "$full" --body "$body" --label "story,sprint-$sprint,sp:$sp,$label" --milestone "Sprint $sprint")
  out=""
  if [ -n "$who" ]; then out="$(gh "${args[@]}" --assignee "$who" 2>&1 </dev/null)"; fi
  case "$out" in
    https://*) ;;
    *) [ -n "$who" ] && echo "  note: could not assign '$who' (not a collaborator?), creating unassigned"
       out="$(gh "${args[@]}" 2>&1 </dev/null)" ;;
  esac
  case "$out" in
    https://*)
      echo "  $out  <- $full"; created=$((created+1))
      if [ -n "$PROJECT_NUMBER" ]; then
        gh project item-add "$PROJECT_NUMBER" --owner "$OWNER" --url "$out" >/dev/null 2>&1 </dev/null || echo "    warn: not added to project"
      fi ;;
    *) echo "  FAILED: $full -> $out"; failed=$((failed+1)) ;;
  esac
done 3<<'DATA'
1|5|backend|1|Technical (SRS 2.1, 3.3)|Set up Flask app structure and SQLite schema|App runs with flask run; tables for users, slots, tickets, reservations and payments are created on first start.|-
1|3|backend|1|PVT-F-001|User registration (name, email, password)|AC-F-001: valid registration creates an account and redirects to login.|TC-Auth-01
1|5|backend|1|PVT-F-002|Login with email and password, issue JWT session token|AC-F-002: valid credentials return a token; invalid credentials show an error.|TC-Auth-02
1|2|backend|1|PVT-F-003|Logout removes the authentication token|AC-F-003: logout clears the token; protected routes become inaccessible.|TC-Auth-03
1|2|backend|1|PVT-NF-005 / PRJ-SR-001|Hash and salt passwords (bcrypt)|AC-SR-001: DB inspection shows only hashed passwords.|TC-Sec-01
2|5|backend|1|PRJ-SR-002|Role-based access control (Admin vs User)|AC-SR-002: unauthorized role access returns 403.|TC-Sec-02
2|5|backend|1|PRJ-SR-004|Validate and sanitize all user inputs|AC-SR-004: no SQL injection or XSS found in testing.|TC-Sec-04
2|3|backend|1|PRJ-SR-005|Lock account after 5 failed login attempts|AC-SR-005: the 6th failed attempt blocks login for 15 minutes.|TC-Sec-05
2|5|backend|1|PVT-F-014|Record payment transaction and generate receipt|AC-F-014: receipt has transaction ID, amount and timestamp.|TC-Pay-01
1|5|parking|2|PVT-F-004|Real-time slot availability by zone|AC-F-004: UI reflects current occupied and free status.|TC-Slot-01
1|2|parking|2|PVT-F-005|Filter slots by vehicle type (two-wheeler / four-wheeler)|AC-F-005: filtered results match the selected type.|TC-Slot-02
1|3|parking|2|PVT-F-015|Admin can add, edit and remove parking slots|AC-F-015: CRUD operations are reflected immediately in the slot listing.|TC-Admin-01
1|5|parking|2|PVT-F-008|Record vehicle entry (vehicle number, slot, timestamp)|AC-F-008: entry record created and slot status updated to occupied.|TC-Track-01
1|5|parking|2|PVT-F-009|Record vehicle exit and free the slot|AC-F-009: exit record created; slot status reverts to available.|TC-Track-02
2|3|parking|2|PVT-F-010|Live occupancy count per zone|AC-F-010: occupancy count matches the sum of occupied slots.|TC-Track-03
2|3|parking|2|PVT-F-011|Entry/exit audit log with timestamps|AC-F-011: logs retrievable via admin view with correct timestamps.|TC-Track-04
2|5|parking|2|PVT-F-012|Calculate parking fee from duration and vehicle type|AC-F-012: fee = rate x billed hours and matches the configured rate table.|TC-Bill-01
2|3|parking|2|PVT-F-013|Show calculated fee before exit confirmation|AC-F-013: fee shown matches the backend calculation.|TC-Bill-02
2|3|parking|2|PVT-F-016|Admin configures hourly rate per vehicle type|AC-F-016: updated rate is applied to new fee calculations.|TC-Admin-02
2|3|parking|2|PVT-F-006|Prevent booking of an occupied or reserved slot|AC-F-006: duplicate booking attempt returns a conflict error.|TC-Slot-03
2|5|parking|2|PVT-F-007|Reserve an available slot for a time window|AC-F-007: successful reservation marks the slot reserved and returns confirmation.|TC-Slot-04
1|3|frontend|3|PVT-NF-004|Base templates and responsive CSS (desktop and mobile)|AC: manual test across 3 screen sizes shows correct layout.|TC-UX-01
1|3|frontend|3|PVT-F-001, PVT-F-002|Login and registration pages|Forms wired to the auth endpoints with clear error messages.|TC-Auth-01, TC-Auth-02
1|5|frontend|3|PVT-F-004, PVT-F-008, PVT-F-009|Slot search, entry and exit pages|Pages show availability and record entry and exit through the parking endpoints.|TC-Slot-01, TC-Track-01, TC-Track-02
2|3|frontend|3|PVT-F-007|Reservation interface|Reservation form with time window and confirmation dialog.|TC-Slot-04
2|5|frontend|3|PVT-F-013, PVT-F-014|Fee display, payment and receipt pages|Fee is shown before exit confirmation; receipt page is shown after payment.|TC-Bill-02, TC-Pay-01
2|5|frontend|3|PVT-F-015, PVT-F-016|Admin dashboard (slots and rates)|Admin can manage slots and hourly rates from the UI.|TC-Admin-01, TC-Admin-02
2|5|frontend|3|PVT-F-017|Daily and monthly occupancy and revenue reports|AC-F-017: report totals match the sum of individual transactions.|TC-Admin-03
1|3|testing-docs|4|Process|Enable GitHub Actions CI|Workflow installs dependencies and runs tests on every push and PR.|-
1|3|testing-docs|4|Sprint 1 scope|Write and run Sprint 1 test cases|Sprint 1 test cases from the Test Plan are executed and results logged.|TC-Auth-01 to 03, TC-Slot-01 to 02, TC-Track-01 to 02
1|2|testing-docs|4|Deliverable|Record Sprint 1 demo video (1 minute)|Working-product video uploaded to the repo.|-
2|5|testing-docs|4|Sprint 2 scope|Test billing, payment, admin and reservation features|Sprint 2 test cases executed; bugs raised as issues and verified.|TC-Slot-03 to 04, TC-Track-03 to 04, TC-Bill-01 to 02, TC-Pay-01, TC-Admin-01 to 03
2|3|testing-docs|4|PVT-NF-001, PVT-NF-002|Performance tests (p90 under 2 s, 50 concurrent users)|AC: load test results recorded against both targets.|TC-Perf-01, TC-Perf-02
2|3|testing-docs|4|PRJ-SR-003|HTTPS/TLS configuration and verification|AC-SR-003: network capture confirms TLS in use.|TC-Sec-03
2|3|testing-docs|4|Deliverable|Documentation, RTM status update and documented deviations|README, setup steps and RTM statuses updated; deviations from SRS/SAD listed.|-
2|2|testing-docs|4|Deliverable|Record Sprint 2 demo video (2 minutes)|Working-product video uploaded to the repo.|-
DATA

echo
echo "Done: $created created, $skipped skipped, $failed failed."
echo "Issues: https://github.com/$REPO/issues"
