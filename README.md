# Job Alerts GR

Phone notifications for new job listings in Greece. Every 15 minutes, a GitHub
Actions job checks **LinkedIn, Kariera.gr and Skywalker.gr** (Indeed GR is optional)
for listings that match your search. Each new one is pushed to your iPhone or
Android phone through the free [ntfy](https://ntfy.sh) app. Tap the alert and the listing opens.

It runs entirely on GitHub's free tier: no server, no paid accounts, no app store.

- `watcher.py` checks the sites and sends alerts. It uses only Python's standard library.
- `config.json` holds your search: job/field keywords, location and which sites to check.
- `docs/` is a settings page (served by GitHub Pages) that you add to your home screen
  to edit the search, pause or resume alerts, and run a check on demand.
- `.github/workflows/watch.yml` runs the check every 15 minutes and whenever the search changes.

## Use it yourself

### 1. Get your own copy
Click **Fork** at the top of this page. Then open your fork's **Actions** tab and click
**I understand my workflows, go ahead and enable them**. GitHub turns off scheduled
workflows in forks until you do this.

Keep the fork **public**. Public repos get unlimited Actions minutes; a private repo
only gets 2,000 minutes a month, which runs out after about 20 days of 15-minute checks.

### 2. Set up ntfy
1. Install **ntfy** on your phone ([iOS](https://apps.apple.com/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) and allow notifications.
2. Tap **+** and subscribe to a topic. Pick a long, random name that nobody could guess.
   Anyone who knows the name can read your alerts.
3. In your fork, go to **Settings → Secrets and variables → Actions → New repository secret**.
   Enter the name `NTFY_TOPIC` and paste your topic name as the value.
   Secrets are never shown publicly.

### 3. Turn on the settings page
**Settings → Pages**: under Source choose *Deploy from a branch*, then pick branch `main` and folder `/docs`.
After about a minute it's live at `https://YOUR-USERNAME.github.io/greek-job-alerts/`.

### 4. Create a token for the settings page
Go to **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**.
- Repository access: *Only select repositories*, then choose your fork
- Permissions: **Contents: Read and write** and **Actions: Read and write**

The token is saved only in your phone's browser. It never goes into the repo.

### 5. Add it to your home screen
1. Open your Pages link in Safari (iPhone) or Chrome (Android).
2. Paste the token and tap **Connect**.
3. Use **Share → Add to Home Screen**.
4. Set the job/field and location, then tap **Save**. Within a couple of minutes ntfy
   shows **"Job alerts are on"**. After that, each new listing arrives as its own alert.

### 6. Make it actually check every 15 minutes
GitHub's built-in schedule is unreliable on free repos and often runs only every
3–6 hours. A free outside timer fixes that by pressing "Check now" for you.

1. Create a second fine-grained token (see step 4) for your fork with only
   **Actions: Read and write**. It can start checks and do nothing else.
2. Sign up at [cron-job.org](https://cron-job.org) (free) and click **Create cronjob**:
   - URL: `https://api.github.com/repos/YOUR-USERNAME/greek-job-alerts/actions/workflows/watch.yml/dispatches`
   - Schedule: every 15 minutes
   - Under **Advanced**:
     - Request method: `POST`
     - Headers: `Authorization: Bearer YOUR-TOKEN` and `Accept: application/vnd.github+json`
     - Request body: `{"ref":"main"}`
3. Save, then use **Test run**. A response of `204` means it worked. The settings page's
   "Last check" time should update within a minute or two.

GitHub's own schedule stays on as a backup in case the timer ever stops.

## Using it

| You want to… | Do this |
|---|---|
| Stop alerts | Flip the big switch to **Paused** |
| Search for something else | Edit the job/field or location and tap **Save**. The first check after a change only records what's already posted, so you won't be flooded with old listings. |
| Check right now | Tap **Check now** |
| See what the last check found | Tap a site's **N matching** in the Status section. New listings are marked **NEW**; tap one to open it. |
| See whether a site is failing | Look at the **Status** section at the bottom |

Tips:
- Start typing in the **Job** search bar, in Greek or English, with or without accents.
  Pick a **field** to search all its English and Greek job titles, or pick a single title.
  Tap the empty bar to browse every field. For anything not listed, choose **Add "…"**.
  Fields and their titles live in `docs/fields.json`; edit that file to add more.
- Choose **All of Greece** to search everywhere. Athens also matches its suburbs (Chalandri, Marousi, Kifisia, …).
- With **Include remote jobs** on, remote listings and ones posted for "Greece" as a whole are included too.

## Good to know
- **Your search is public.** In a public repo, anyone can see `config.json` (your keywords
  and location) and the list of jobs already sent. Your ntfy topic and token stay private.
- **Indeed often blocks automated requests.** If its status shows "couldn't load", switch it off.
- **xe.gr and JobFind.gr aren't supported.** Their listings only load inside a browser.
- **Sites change their layouts.** If one shows "couldn't load" for days, its reader
  in `watcher.py` needs updating.
- **Already-sent jobs are remembered in `seen.json`.** That's how you never get the same job twice.
  The file is cleared when you change your search. A job is forgotten once it has been gone
  from results for 30 days, so the file doesn't grow forever.
- **What counts as new:** LinkedIn is checked for jobs posted in the last 24 hours,
  and Kariera for its newest 150 listings.
- **Token expiry:** when your token expires, the settings page shows an error. Alerts keep
  coming in the meantime. Create a new token and reconnect.
