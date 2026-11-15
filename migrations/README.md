# Database upgrade notes

Back up `instance/parking.db` before first running this branch against existing
data. Stop other application writers while upgrading. The new factory applies
Alembic revisions on startup for the local application; `python -m flask --app
run db-upgrade` explicitly applies the same versioned upgrade.

- `0001` adopts/creates the prototype tables, adding older missing columns while
  preserving records.
- `0002` adds persistent JWT sessions, vehicle-type rates, integer-cent amounts,
  entry-rate snapshots, audit events and state-operation indexes.
- An explicit SQLite transaction wraps all DDL and data conversion. An error
  rolls the attempted revision back. Duplicate payments or duplicate active
  visit logs cause a clear refusal; rows are never silently removed.

## Existing timestamps

If reservations already exist, the upgrade requires an explicit declaration of
their original timezone. The old browser code used the server's local time;
PR #51's lockout deadlines were already UTC. For a prototype run in India:

```powershell
$env:VPS_LEGACY_TIMEZONE = "Asia/Kolkata"
python -m flask --app run db-upgrade
```

Use `UTC` instead if the historical reservation/log/payment timestamps were UTC.
The conversion affects those timestamps once, not existing lockout deadlines.
Fresh databases need no setting. Mixed historical timezones require manual
review against a backup; do not guess. The tracked legacy `vps.db` belongs to the
retired application and is never automatically imported over canonical data.

## Existing rates and rollback

Active visits receive their previous slot rate as a snapshot. For each vehicle
type, the lowest existing slot rate initializes the shared type rate, then all
slots of that type display that rate. Review/configure both type rates in Admin
before new visits. Existing paid fees are preserved and copied to integer cents.

`0002` has a structural downgrade for development, but it removes new session,
rate and audit data. Restore the tested pre-upgrade backup for an operational
rollback, including original timezone interpretation. The baseline downgrade
intentionally refuses to destroy original user/transaction tables.
