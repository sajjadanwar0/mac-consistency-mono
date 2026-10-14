# PetroTrack handoff prompt (8 Oct 2026)

Copy everything below the line into a new Claude session as its first message. It contains no passwords or tokens.

---

Hi. I'm continuing a project called **PetroTrack**. It's a fuel station web portal for a client in Ghana. We built it from my attendance app: we kept the auth and the authorization and removed everything specific to attendance. It's Laravel / React / TypeScript / Tailwind and runs in Docker on my machine at **fuel.test**. Everything below is the current state, so please read it all before you start. Then read the files I point to, set up PHP 8.4 on your system, and carry on with what's remaining.

## Where everything is

All of it is in the project's shared folder, `/mnt/project-files/`:

- `fuel-starter/petrotrack/` is **the current code**. It's the same as what I have locally after running every fix script so far. Read `README.md` (auth and permissions), `SETUP.md` (the long setup), `RUN-LOCALLY.md`, `CALCULATIONS.md` (every formula and where it came from) and `AUDIT.md` (the last audit) first.
- `fuel-starter/petrotrack.zip` is an **old copy**. Ignore it.
- `fuel-starter/fixes/` holds the fix scripts I've already run: `1_backend_fix.sh`, `1_frontend_fix.sh`, `2_frontend_fix.sh`. Use them as the template for new ones.
- `fuel-starter/guides/` holds `PetroTrack-Hostinger-Deploy-Guide.pdf` and `PetroTrack-Docker-Setup-Guide.pdf`.
- `fuel-starter/screenshots/` has screenshots of the dashboard and shift log.
- `uploads/hearth/836b13ff-b4be-42b6-bef0-36379b780fbf` is the **client's mockup** (one HTML file, "PetroTrack Ghana"). It's the source for every screen and formula.
- `attendance.zip` is my original attendance app, the source of the patterns. **It contains real secrets and personal data** (.env files, an SQL backup, employee CSVs, logs). Never copy any of that out.
- `best-practices-books.zip` holds the books (see below).
- `.notes/inputs.md` has notes on each file I've uploaded.

My private GitHub repo is `sajjadanwar0/petro-track`. It isn't attached to these sessions, so the shared folder is the source of truth, and I push to GitHub myself.

## What the app is

- **Backend:** Laravel 13 on PHP 8.4. It uses DDD-style domains in `backend/src/Domain/` (Access, Fuel, Reporting, Settings, Shared), single-action invokable controllers, actions with a static `execute`, view models and spatie/laravel-data objects. Deptrac enforces that a domain depends only on Shared. Tests are Pest, and the suite runs on in-memory SQLite.
- **Frontend:** React 19, TypeScript, Vite, Tailwind v4, TanStack Query, react-hook-form with Zod, and Chart.js 4.5 with react-chartjs-2.
- **Docker:** `compose.yaml` runs MySQL, PHP (`docker/php/Dockerfile`, php:8.4-fpm), the queue, the scheduler, nginx, Mailpit and Vite. The helper is `./fuel` (`./fuel up`, `./fuel artisan …`, `./fuel test`, `./fuel check`). Env variables use the `FUEL_` prefix.
- **Roles:** System Admin (two-factor forced, onboards stations), Business Owner (dashboard, history and export, station prices) and Station Manager (logs and locks shifts). The seed accounts are admin@, owner@ and station@example.test, with the password from `FUEL_SEED_PASSWORD`.
- **Screens that are real now:**
  - **Shift Log** calculates live as you type, using the mockup's formulas, and the server recalculates when the shift is locked. Money is held as integer pesewas and litres as centilitres, rounded half up. Opening meter, opening dip and price come from the previous shift and are read-only. A locked shift is never edited.
  - **Shift History** has filters, prefix search, export and a detail page for each shift.
  - **Stations** has onboarding and price changes.
  - **The owner dashboard** looks like the mockup, drawn with Chart.js: four figure cards, a revenue-and-litres dual-axis trend, a product doughnut, rule-engine recommendations and the five latest shifts.
- The backend and frontend are tested against the same cases: `backend/tests/Fixtures/reconciliation-cases.json` and the frontend copy must stay identical.
- Last known results: backend 591 tests passing (7 skipped), frontend 329 tests passing, and every gate green.

## The books, and how we audit

The books are in `/mnt/project-files/best-practices-books.zip`. You must follow them **strictly** and audit **brutally** against them.

1. **Domain-Driven Design with Laravel** (PDF inside a zip). This is the backend architecture: domains, actions, data objects, view models, aggregating in SQL, no queries in loops, money as value objects.
2. **Indexing Beyond the Basics** by Tobias Petry (PDF inside a zip). This covers every query and migration: no leading-wildcard LIKE, left-to-right composite indexes, ORDER BY served by an index, no index added "just in case", and EXPLAIN on real data.
3. **laravel-best-practices.zip**. This is **about 195 screenshots of tips (JPEG/PNG), not text**, so you have to read each image. The last audit split them into two tip sets, cited as "Laravel-1 §x.y" and "Laravel-2 Xn" (for example `whereBelongsTo`, `enforceMorphMap`, `env()` only in config, rate limits per user).
4. **React Design Patterns and Best Practices** by Carlos Santana Roldán (PDF). This is the frontend: loading, error-with-retry and empty states, derived state in render, server state in Query, API calls kept in `lib/`, schema validation, error boundaries, accessibility, and tests that query by role.

**How the audit works** (`AUDIT.md` shows the format):
- First, read each book and turn it into a numbered digest of rules plus a checklist. The digests from the last round lived in a temporary folder and are **gone**, so rebuild them and **save them this time** in `/mnt/project-files/fuel-starter/book-digests/` so later sessions can reuse them.
- Run one audit pass per side: the backend against books 1 to 3, and the frontend against book 4. Do the code you changed first, then the rest of the code.
- Write every finding as a table row: **Book (digest and rule) | Where (file:line) | Finding | Fix made, or "left, because …"**. Fix every finding unless there's a concrete reason not to, and write that reason down. "Compliant, no change" rows are fine where you checked something.
- Back every fix with a test where it can be tested, and do a sabotage check (break the fix and make sure the test fails).
- Then run all the gates, and append the new round to `AUDIT.md` with the date. Don't overwrite the old rounds.
  - **Backend gates:** Pint (`--test`), PHPStan (no errors), Deptrac (0 violations, 0 errors), `php artisan idioms:baseline --check`, and the full Pest suite.
  - **Frontend gates:** `prettier --check`, `tsc -b`, `oxlint --deny-warnings --report-unused-disable-directives`, and `vitest run` (the test timeout is 15s).
- Finally, check the screens in a real browser (Playwright/Chromium) with demo data, as each role.

## How I want things delivered

- **No zip files, ever.**
- Setup is done by numbered bash scripts, backend and frontend separately. These already exist: `scripts/backend/1-…6-` and `scripts/frontend/1-…5-`.
- **Changes to my code come as downloadable fix scripts, and this round's numbering starts again at 1:** `1_backend_fix.sh` and `1_frontend_fix.sh`, then `2_…`, and so on. Copy how the existing scripts in `fuel-starter/fixes/` behave:
  - Each one runs from `backend/` (`cd backend && bash ../1_backend_fix.sh`) or `frontend/`, and refuses to run anywhere else.
  - It writes each file whole, and checks known hashes, so a file I edited by hand is copied to `../petrotrack-fix-backups/<script>-<timestamp>/` before it's replaced.
  - Afterwards it runs migrations and every check, unless I pass `--no-checks`.
  - You run every script end to end on a copy of the current code before giving it to me.
  - Put the new round in `fuel-starter/fixes/` without overwriting the old scripts. Move the old ones into `fixes/round-1/` first.
  - Also update `fuel-starter/petrotrack/` so it stays the current code.
- Deploys are plain commands. The backend is pulled from GitHub on the server. The frontend is built on my machine and rsynced, assets first and `index.html` last, the same way my meal app does it:
  ```
  rsync -az --exclude index.html frontend/dist/ <ssh-alias>:<web folder>/
  rsync -az frontend/dist/index.html <ssh-alias>:<web folder>/index.html
  ```
  Laravel's `routes/web.php` catch-all serves `public/index.html` with `Cache-Control: no-cache, must-revalidate` and excludes `api/`, `sanctum/` and `up`.
- Guides come as PDFs.
- Never put a password or token in a file, a script, or a git remote URL.

## How to set up PHP

**On your own system (to run the backend checks).** The app requires `php ^8.4`. Your sandbox may ship with PHP 8.3 (Ubuntu 24.04 does), and that won't work. Install 8.4 first:
```
sudo add-apt-repository -y ppa:ondrej/php && sudo apt-get update
sudo apt-get install -y php8.4-cli php8.4-mbstring php8.4-xml php8.4-intl php8.4-zip php8.4-gd \
  php8.4-bcmath php8.4-sqlite3 php8.4-mysql php8.4-curl
sudo update-alternatives --set php /usr/bin/php8.4 && php -v
cd backend && composer install && ./vendor/bin/pest
```
If the PPA is blocked, build a small stand-in Docker image (Ubuntu plus PHP 8.4 from whatever source is reachable) and run the checks in it. That's what the last session did, because Docker Hub's PHP mirror was blocked. Tests only need the CLI with pdo_sqlite. MySQL is only needed for the full Docker smoke test.

**On my laptop.** PHP lives inside Docker (`docker/php/Dockerfile`, php:8.4-fpm, with pdo_mysql, bcmath, gd, intl, zip, opcache, exif and pcntl). Nothing needs installing on the host except Docker.

**On my Hostinger server.** The default CLI is **PHP 8.5.9**, which phpspreadsheet 1.30 (pulled in by maatwebsite/excel) refuses. So I use 8.4:
```
mkdir -p ~/bin84 && ln -sfn /opt/alt/php84/usr/bin/php ~/bin84/php
echo 'export PATH=~/bin84:$PATH' >> ~/.bashrc && export PATH=~/bin84:$PATH && php -v
php $(command -v composer) install --no-dev --optimize-autoloader --no-interaction
```
Also set the website itself to 8.4 in hPanel (Advanced → PHP Configuration). The cron, which runs every minute, uses the 8.4 binary:
`cd /home/u941588300/petro-track/backend && /opt/alt/php84/usr/bin/php artisan schedule:run > /dev/null 2>&1`.
The `/opt/alt/php84` path is assumed and hasn't been confirmed on my server.

## The demo deploy (Hostinger shared hosting)

- **Host:** Business Web Hosting. The SSH user is u941588300, and the main site is capripackages.com.pk (WordPress, in `~/domains/capripackages.com.pk/public_html`).
- **Layout:**
  - The app is cloned at `~/petro-track`.
  - `public_html/petrotrack` is a symlink to `~/petro-track/backend/public`, served at petrotrack.capripackages.com.pk.
  - My meal app lives on the same server.
- **`.env` for the demo:** `QUEUE_CONNECTION=sync`, `MAIL_MAILER=log`, and the full demo seed (`db:seed`). A live install would use `DeploymentSeeder`, which seeds no demo stations.
- **Deploy scripts:** `scripts/deploy/server/1-check-host … 6-finish` run once, and `7-update` runs on each release. `scripts/deploy/laptop/1-check-connection … 4-upload-frontend` run on each release, and their settings are in `.deploy.env`. They were tested against a stand-in Hostinger container, not my real server.
- The server scripts refuse a clone whose origin URL contains a token, and they refuse unpushed commits.

## What's remaining

**Things on my side that nobody has confirmed yet.** Ask me about these before assuming anything:
1. Whether the demo at petrotrack.capripackages.com.pk actually works. My last report was the composer failure on PHP 8.5, and I switched to 8.4 after that.
2. Whether `backend/composer.lock` and `scripts/deploy/` are pushed to my GitHub. The lock file was missing there, and I was told to use `git add -f`.
3. Whether I've revoked the GitHub token I cloned with, and re-pointed the server's origin to a read-only deploy key (SSH over ssh.github.com:443).
4. Whether I've run `1_backend_fix.sh`. I ran `1_frontend_fix.sh` and `2_frontend_fix.sh`.
5. My real `php:8.4-fpm` Docker image has never been built in the cloud, only a stand-in. `scripts/backend/5-serve-on-port-80.sh` has never been run.

**Code follow-ups from the last audit:**
1. **Station managers aren't scoped to their own station.** A manager can log shifts for any station. Add a user-to-station assignment and enforce it in the shift log, history and dashboard.
2. **No morph map.** `Relation::enforceMorphMap` isn't on, so `activity_log` and `personal_access_tokens` store class names. This needs a data migration that rewrites the existing `*_type` values, plus a fix to `ActivityEntry::subjectLabel()`.
3. **The shared table's error row** (`components/table/ServerDataTable`) still says "Refresh the page to try again". It needs a real Try again that refetches, as the React book's rule #8 requires. Every register uses that table.
4. **`noUncheckedIndexedAccess`** isn't on in `tsconfig.app.json`. Turning it on gives about 56 errors: about 20 in source and 36 in tests.
5. **The React Compiler isn't actually enabled.** Only its lint rules run. The `useMemo`s around the charts stay until it's enabled.
6. **From the client's mockup:** the printable **"Shift Audit Reconciliation Certificate"** isn't built. Compare the mockup screen by screen with the app and list anything else that's missing.
7. Revisit the index decisions in `AUDIT.md` with EXPLAIN once there's real data.

## What I want from you now

1. Read the files above and the mockup. Rebuild the book digests and save them.
2. Install PHP 8.4 on your system and run every backend and frontend gate on `fuel-starter/petrotrack/`, so we both know the baseline is green.
3. Work through the remaining code follow-ups, highest impact first (station scoping first), following the books strictly. Audit brutally and record each round in `AUDIT.md`.
4. Give me the changes as `1_backend_fix.sh` and `1_frontend_fix.sh` (then 2, 3, …), each run end to end here first. Tell me exactly what to run, in which folder, and what to deploy.
