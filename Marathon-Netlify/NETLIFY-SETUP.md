# Stephen’s private marathon app — Netlify + hourly Garmin sync

This replaces the Oracle/Render hosting instructions for the hosted version. Your existing Mac app still runs with Start.command.

## What changed

Netlify runs the private web login and API as a Node function. Netlify Blobs holds the dashboard, server-side sessions, queued check-ins, and an encrypted copy of the Python database and Garmin tokens. The dashboard is only accessible after signing in. No personal dashboard, baseline plan, or SQLite file is published as a static asset.

A GitHub Actions job runs the original Python Garmin client and conservative planner at minute 17 of each hour, even when your Mac is off. Check-ins, mode changes, undo and approvals are queued immediately and processed on the next successful run. Old check-ins retain their original Chicago date and cannot rewrite past workouts. On reported pain, stop and reassess now rather than waiting for a plan update.

There is **no 5–10 minute sync guarantee** in this free configuration. GitHub schedules can be late or skipped, outages and Garmin authentication failures can stop updates, and public-repository schedules can be disabled after 60 days without repository activity. The journal shows the last successful Garmin sync and pending reviews. Use Actions → Garmin sync → Run workflow for an occasional manual refresh. Keep the repository private for personal code/data settings; never commit runtime data or keys.

## Free usage and limits

Choose Netlify’s **Free** plan and do not enable a paid plan or auto-recharge. The current Free plan has a fixed monthly credit allowance; the site can pause when it is exhausted. Other sites under the same account can consume that allowance too.

GitHub Free includes 2,000 Actions minutes/month for private repositories. Hourly jobs mean at most 744 scheduled starts in a 31-day month; the workflow has a two-minute timeout to target less than 1,488 job minutes before other workflows/manual runs. This is a capacity estimate, not a billing guarantee. Keep GitHub Actions paid spending blocked (no payment method, or a $0 budget with “Stop usage when budget limit is reached” enabled). Do not approve a paid upgrade. If a run consistently times out, stop the schedule and review the job rather than increasing paid limits.

References checked October 21, 2026:
- https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/credit-based-pricing-plans/
- https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/billing-faq-for-credit-based-plans/
- https://docs.github.com/en/billing/reference/product-usage-included
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

## 1. Update GitHub

The extracted project root contains `netlify.toml`, `package.json`, `netlify/`, `tools/`, `.github/`, and `austin-plan/`. These all belong at the root of the existing marathon-training repository. Do not nest the entire new folder inside the old austin-plan folder.

Use GitHub Desktop to clone your existing repository, copy this package’s files into that checkout, review changes, commit, and push. On macOS use Command+Shift+Period in Finder to show hidden files so `.github/` and `.gitignore` are copied too. If uploading via GitHub’s website, also explicitly include those hidden files. Never copy your working app’s data or virtual environment.

The project ZIP contains source code and test fixtures only. It contains no Garmin login, user database, or hosted keys.

## 2. Create the Netlify project

In Netlify, choose Add new project → Import an existing project → GitHub → marathon-training.

- Plan: Free.
- Production branch: your main/default branch.
- Base directory: leave blank (repository root).
- Build command: `npm run build`.
- Publish directory: `netlify-public`.
- Functions directory: `netlify/functions` (read from netlify.toml).

Deploy. Before secrets are configured, the app returns “Complete the hosting configuration first.” That is expected and safe. Copy the main production HTTPS address; keep this address unchanged during setup. Preview deployments are blocked from reading or writing the production journal. Do not use a deploy-preview URL.

## 3. Connect securely on your Mac

On the Mac where Garmin already syncs successfully, extract this project package and double-click **Connect-Hosting.command**. If macOS blocks it, open Terminal, type `bash ` (including the space), drag the command file into Terminal, then press Return.

The connector uses your existing Python 3.12 installation and makes a separate hosting setup environment. It does not replace the working app or its virtual environment. It asks for your Netlify address, working app path, and a NEW website password (14+ characters). Password entry stays hidden.

The wizard copies one value at a time to your clipboard and tells you where to paste it. It never prints secret values. Follow its Return prompts only after saving each value.

**Netlify → Project configuration → Environment variables:**
- APP_ORIGIN
- ADMIN_PASSWORD_HASH
- WORKER_SECRET

Keep these available to production Functions (or all scopes on Free). Do not create them in netlify.toml or source files.

**GitHub repository → Settings → Secrets and variables → Actions → New repository secret:**
- APP_ORIGIN
- WORKER_SECRET
- STATE_KEY

STATE_KEY belongs in GitHub Actions secrets only. Garmin account credentials are not entered in Netlify or chat. The wizard encrypts the locally saved token files before uploading them. The key can decrypt the hosted state, so keep it private. A recoverable local copy of this hosting configuration is saved in the working app’s `data/hosting-secrets.json`, with owner-only permissions; never upload that data folder or the configuration file to GitHub or chat.

After adding the variables, trigger another production deploy in Netlify and wait for Published. Return to the wizard and press Return to seed the hosted journal. It copies local state using SQLite’s backup API and does not alter your local plan or activities. Local web sessions and the local login password are excluded. An interrupted setup can be rerun; saved keys are reused and existing hosted state is not overwritten.

## 4. Run and verify

GitHub → Actions → Garmin sync → Run workflow → Run workflow. Wait for the job to finish successfully. Open the main Netlify address, sign in with the new app password, and confirm your activities and “Last successful sync” timestamp. Submit a check-in: it should show that the review is pending. After the next hourly run, refresh to see the saved check-in and any applicable adjustment.

Log out and confirm that the dashboard and `/api/dashboard` require sign-in. Verify GitHub Actions spending remains blocked and Netlify is still on Free. No deployment has been performed by this package.

## Recovery and backups

Keep the working local app and its private data folder as a backup. The hosted store survives deploys, but deleting the Netlify project or its blob store can destroy hosted history. Keep STATE_KEY available in your password manager or another secure offline backup; without it, encrypted hosted state cannot be recovered. Do not manually change STATE_KEY after setup.

If Garmin expires the hosted session, reauthenticate Garmin locally first. Rerun Connect-Hosting.command with the same address and working app folder; it reuses the saved keys. When prompted about the existing hosted journal, answer y to refresh ONLY its Garmin tokens. Hosted activities, check-ins and plan history are preserved, and queued actions remain queued. Then run the GitHub workflow. Never delete the hosted store just to reconnect Garmin.

Changing the local password does not change the website password. Changing ADMIN_PASSWORD_HASH on Netlify and redeploying invalidates old hosted sessions. Worker errors log only safe error types, not tokens or raw Garmin responses. All training information remains under your GitHub/Netlify account controls; it is not sent to an AI service.

## Validation and remaining limits

Local checks cover authenticated/private routes, CSRF, sessions/logout/password changes, concurrent login throttling, queued actions with concurrent worker commits, encrypted state integrity/restore, command replay, delayed check-ins, and the existing planner rules. The dependency lock and Netlify function bundle are checked locally. Hosted Netlify routing/storage, real GitHub scheduling, real Garmin authentication, and browser appearance still require verification in your actual deployment. No hosted accounts were accessed or changed while preparing this package.
