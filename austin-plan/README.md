> **Netlify hosting:** use the repository-root `NETLIFY-SETUP.md` and `Connect-Hosting.command`. Hosted Garmin sync and plan reviews run hourly. The Render/Docker instructions below are an alternative paid deployment, not the current free hosting path.

# Stephen — live marathon journal

Private running journal for Austin Marathon, February 14, 2027, goal 3:40.
The goal remains a stretch target; the program does not infer race readiness from a few easy runs.

## Install the update on your Mac

Unzip the delivered folder and double-click **Update-App.command** beside this `austin-plan` directory. It finds your existing app, backs up the source files it replaces, preserves your local plan.json, and leaves data/ and .venv untouched. It prefers the recognized project currently serving port 8765; otherwise Documents/Codex/2026-10-20/austin-plan, then Downloads/austin-plan. It shows the chosen destination before launching.

The launcher reuses your saved app password and Garmin session. If these are missing in the selected copy, enter them yourself in the private Terminal prompts. Keep the running Terminal open. Password typing is invisible. No real credentials or account data are included in this release.

## What updates live

Garmin is checked every ten minutes while the service is healthy. Failures back off to up to one hour. The plan evaluator runs every minute, and the page refreshes its data every minute while visible. A hosted, always-on instance continues with your Mac off; the local Mac instance does not.

The eight weeks preceding the plan start are included in initial history import. Existing activity IDs are updated rather than duplicated. The app imports running activities from your account; optionally set GARMIN_DEVICE_ID to your watch's actual numeric device ID (not the model number 970) to restrict devices.

The plan and check-ins are private behind login. Source baseline is public/plan.json, served only after authentication. Adjustments, check-ins and history are stored in the existing SQLite database under data/, so source deployments do not erase them. Replacing the baseline plan intentionally resets the active adjusted schedule while retaining history and check-ins.

## Adaptation rules in this version

The rules are transparent planning heuristics, not medical assessments or an AI coach. They never change your goal, race date, past workouts, or dates with recorded completed runs. Automatic adjustments only reduce upcoming work, including today's uncompleted session. New mileage is never automatically added.

- A pain check-in or soreness/fatigue score 4–5 pauses uncompleted running over the next 48 hours. Reassess with a new check-in; use Undo if appropriate. Persistent/localized pain or changed gait needs assessment rather than training progression.
- Soreness/fatigue 3, or last workout effort 8–10, reduces upcoming 48-hour running by about 25% and removes optional speed and leg strength.
- After a completed week below 75% of its scheduled mileage, remaining current-week running is capped toward last week's actual distance + 3 miles. A grace period until Tuesday noon allows late uploads. This rule requires a successful sync within 24 hours; stale/missing sync is not treated as skipped training.
- A recent run over 2h45, or at least two miles and 25% beyond its planned distance, can ease the next 48 hours.
- The next long run is capped at the largest completed distance in the preceding 28 days + 1 mile.
- Missed runs stay missed. They are not moved to rest days or stacked as catch-up mileage. This version does not automatically reschedule missed sessions.
- After two weeks meeting at least 90% of their adjusted target, plus a recent check-in with low soreness/fatigue and no pain, the app may propose restoring up to 5% of an upcoming reduced week's mileage. This requires approval, a fresh Garmin sync, never exceeds the original plan, adds no speed or new running days, and is disabled during the last three weeks.
- Each adjustment explains its reason. Undo restores only the latest adjustment and only for dates that are not past/completed. Undone events are remembered so the same event doesn't immediately reapply. Automatic mode can be paused.

Heart rate, pace, time and mileage remain visible, but pace/HR changes alone do not trigger a diagnosis or automatically change intensity. Heat, terrain, sensor error and missing context can explain those changes. This version uses mileage/time, consistency and your check-in scores for changes. It does not consume Garmin sleep, HRV, Training Readiness, or strength activities.

## Verification

- 27 tests pass: adjustment bounds, completed/race protection, stale-sync handling, persistence, mode pause, undo, approval freshness/ceiling, private endpoints, CSRF and Garmin activity deduplication.
- Real Gunicorn HTTP smoke test passes using a disposable account: login, private assets, check-in, automatic change, undo, origin rejection and logout.
- JavaScript syntax and Python compilation pass. HTML assets resolve.
- Pinned Garmin library installed and its token-backed login and get_activities interfaces inspected. Live Garmin authentication/fetch was not attempted with your account; your existing working token storage remains in place on your Mac.
- Visual browser QA could not reach the isolated local test server from the available browser. Browser rendering on Mac/mobile and Docker image execution remain unverified. Docker is not installed in this workspace. Gunicorn itself was exercised successfully.

Run checks from this folder:

    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python tests/http_smoke.py

## Put it on an actual website — cost before deployment

Prepared target: one Render Docker web service, single Starter instance, one 1 GB persistent disk at /data, HTTPS, Hobby workspace. Estimated base **$7.25/month**: Starter $7/month plus disk $0.25/GB/month. Hobby workspace has no base workspace fee. Taxes, excess outbound traffic, build overages, optional domain registration, extra services or a paid workspace plan add cost. No custom domain is needed; Render supplies an onrender.com address and TLS. Confirm the displayed total in the provider dashboard before creating anything paid.

Official sources checked October 20, 2026:
- Starter compute: https://render.com/articles/render-vs-railway (always-on cost table).
- Disk and workspace/usage charges: https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses .
- Persistent disks: https://render.com/docs/disks .
- Shell access: https://render.com/docs/ssh .

A sleeping free service does not meet continuous sync requirements and cannot attach persistent storage. No separate database, worker service, AI API subscription or paid custom domain is needed for this design. The background work shares the one web service. Keep one instance and one Gunicorn process; multiple instances/workers would create duplicate pollers.

This package is PREPARED, NOT DEPLOYED. No hosting account, source repository, paid instance or public app was created in this request. The ChatGPT Sites runtime uses Cloudflare Workers, which cannot directly run this Python/Garmin process; publishing a static shell there would not satisfy the requested sync.

### Deployment steps after accepting the cost

1. Put this cleaned source into a private Git repository. Do not include data/, .venv, .env files, bytecode, or update backups. This release archive excludes all of those.
2. In Render, create a Docker web service from that repository. Review render.yaml; applying it creates a paid resource. Choose Starter, one instance, Hobby workspace, a 1 GB persistent disk at /data. Health check is /health.
3. Set APP_ORIGIN to the exact HTTPS origin Render assigns, with no path (for example https://your-chosen-name.onrender.com). The production entrypoint refuses missing/non-HTTPS origins. DATA_DIR=/data, SYNC_ENABLED=1, BACKGROUND_ENABLED=1. Leave login-secret environment variables unset unless deliberately using an existing password hash.
4. Deploy from the Dockerfile. It installs the pinned lockfile, initializes volume ownership, and drops root access before starting the web service. All application responses use no-store; the private API and files require login. Tokens never belong in the browser or repository.
5. In the host's private interactive Shell, run `python -m server.setup password` and `python -m server.setup garmin`. You type credentials there, not into chat. This creates a new hosted app password and Garmin session; your local app is unaffected. If the shell is root, first use `su -s /bin/sh runner` so token ownership matches the service. Do not paste token contents into chat. Garmin may challenge or rate-limit a new hosting-network sign-in; don't repeatedly retry while blocked.
6. Verify HTTPS login, denial of signed-out API access, a successful Garmin sync, and a newly uploaded activity arriving within ten minutes. Save a recovery check-in and verify any change history. Close the local Mac app to confirm hosted sync runs independently.

If you need to migrate your existing adjusted plan/check-ins/history instead of starting the hosted database fresh, move a consistent data backup through the provider's authenticated private transfer path. This is host-specific and has not been performed. Protect the transfer and backup as account secrets; never attach it here. Activity history itself will reimport from Garmin, but subjective check-ins and revision history will not reimport without the database.

Use host disk snapshots/private backups. Password rotation via server.setup password revokes existing app sessions. The unofficial Garmin library can need maintenance when Garmin changes authentication. Source: https://github.com/cyberjunky/python-garminconnect .
