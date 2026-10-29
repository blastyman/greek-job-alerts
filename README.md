# Job Alerts GR

Get a notification on your iPhone every time a new job is posted in Greece that
matches what you're looking for. It checks **LinkedIn, Kariera.gr and Skywalker.gr**
(and optionally Indeed GR) every 15 minutes, all day, until you switch it off.

How it works:

- **GitHub Actions** runs `watcher.py` every 15 minutes for free, even when your PC is off.
- New jobs are sent to your phone through the free **ntfy** app. Tap an alert to open the listing.
- A **settings page** (GitHub Pages) that you add to your home screen lets you change
  the job/field and location, pause or resume alerts, and run a check right away.

## Setup (about 10 minutes, one time)

### 1. Install ntfy on your iPhone
1. Install **ntfy** from the App Store and allow notifications.
2. Tap **+** and subscribe to a topic. Pick a long, random name nobody could guess,
   for example `jobs-stelios-8f3k29xq`. Anyone who knows the name can read your alerts.

### 2. Put this folder on GitHub
1. Go to <https://github.com/new>, name the repository `greek-job-alerts`, choose **Public**
   (public repos get unlimited free Actions minutes), and create it.
2. Upload every file in this folder, including the `.github` and `docs` folders.
   Either use the page's "uploading an existing file" link, or run this from the folder:
   ```
   git init -b main
   git add .
   git commit -m "Job alerts"
   git remote add origin https://github.com/YOUR-USERNAME/greek-job-alerts.git
   git push -u origin main
   ```

### 3. Tell GitHub your ntfy topic
Repository → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `NTFY_TOPIC`
- Value: the topic name from step 1

### 4. Turn on the settings page
Repository → **Settings → Pages** → Source: *Deploy from a branch* → Branch `main`, folder `/docs` → Save.
After a minute it's live at `https://YOUR-USERNAME.github.io/greek-job-alerts/`.

### 5. Make a token for the settings page
GitHub → your avatar → **Settings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate new token**
- Repository access: *Only select repositories* → `greek-job-alerts`
- Permissions: **Contents: Read and write**, **Actions: Read and write**
- Expiration: up to 1 year (you'll need to make a new one when it runs out)

### 6. Add it to your home screen
1. On your iPhone, open the Pages link in **Safari**.
2. Paste the token and tap **Connect**.
3. Tap **Share → Add to Home Screen**. It now opens like an app.
4. Set your job/field and location, then tap **Save**. Within a couple of minutes you'll
   get a "Job alerts are on" notification. After that, each new listing arrives as its own alert.

## Using it

| You want to… | Do this |
|---|---|
| Stop alerts | Flip the big switch to **Paused** |
| Search for something else | Change the job/field or location and tap **Save** (the first check sets a new baseline, so you won't get flooded with old listings) |
| Check right now | **Check now** |
| See if a site is failing | The **Status** section at the bottom |

Tips:
- Add both English and Greek terms, e.g. `accountant` and `λογιστής`. Kariera and Skywalker
  have many listings written only in Greek.
- Leave the location empty to search all of Greece.
- With **Include remote jobs** on, you also get remote listings and ones posted for "Greece" in general.

## Good to know
- **Indeed is off by default.** It blocks automated requests (it refused them during testing),
  so you can switch it on but expect it to show "couldn't load".
- **xe.gr and JobFind.gr aren't included.** Their listings only load inside a browser,
  so a background checker can't read them reliably.
- **A site may change its layout.** If one shows "couldn't load" for days, its reader
  in `watcher.py` needs updating.
- **Timing isn't exact.** GitHub sometimes runs scheduled checks a few minutes late.
- **What counts as "new":** LinkedIn is checked for jobs posted in the last 24 hours,
  and Kariera for its newest 150 listings.
