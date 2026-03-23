# AutoMagicAI 🎬

Automates AI video generation on [MagicLight.AI](https://magiclight.ai) — reads stories from a Google Sheet, generates **Kids Story Videos**, downloads the video & thumbnail, uploads them to **Google Drive**, and writes all results back to the sheet.

---

## Features

- ✅ Cookie-based login (logs in once, reuses session on next runs)
- ✅ Reads stories from a Google Sheet
- ✅ Skips rows already marked **Generated**
- ✅ Saves the **Project URL** to the sheet right after Step 1 (for retry)
- ✅ Automatically retries using saved Project URL if a row is marked **Pending**
- ✅ Navigates the full 4-step Kids Story generation flow
- ✅ Selects: Pixar 2.0 style · 16:9 ratio · 1 min · English · GPT-4 · Ethan voice
- ✅ Waits for video render (configurable — default 15 min)
- ✅ Downloads **video** + **Magic Thumbnail** into a named local folder
- ✅ Uploads both to **Google Drive** (per-story subfolder, same name)
- ✅ Updates Google Sheet: Status, Magic Thumbnail URL, Video ID, Generated Title, Summary, Hashtags, Notes, Project URL
- ✅ All timeouts configurable via `.env` — no code changes needed
- ✅ Graceful CTRL+C shutdown

---

## Google Sheet Column Structure

| Col | Header | Description |
|-----|--------|-------------|
| A | Theme | Story theme/category |
| B | Title | Story title |
| C | Story Text | Full story content |
| D | Moral | Moral of the story |
| E | Hashtags | Input hashtags |
| F | Date & Time | Submission date |
| G | Status | `Pending` → `Generated` or `Error` |
| H | Magic Thumbnail | Drive URL of the thumbnail |
| I | VideoID | MagicLight project ID |
| J | Title | AI-generated title |
| K | Summary | AI-generated summary |
| L | Hashtags | AI-generated hashtags |
| M | Notes | Processing notes |
| N | Project URL | MagicLight edit URL (for retries) |

- Rows where **Status = "Generated"** are **skipped**
- Rows with empty **Story Text** are **skipped**
- Rows with a **Project URL** and **Status ≠ Generated** are treated as retry jobs

---

## Project Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Google Service Account (Sheets + Drive access)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** → Download JSON key → Save as `credentials.json`
4. Share your Google Sheet and Drive folder with the service account email

### 3. Configure `.env`

Copy `.env.example` to `.env` and fill in your values:

```ini
ML_EMAIL=your_magiclight_email@example.com
ML_PASSWORD=your_magiclight_password
SPREADSHEET_ID=your_spreadsheet_id_here
GOOGLE_DRIVE_FOLDER_ID=your_google_drive_folder_id_here
STORIES_PER_RUN=2

# Timing controls (seconds) — increase if your connection is slow
STEP1_WAIT=60
STEP2_WAIT=20
STEP3_WAIT=180
STEP4_RENDER_TIMEOUT=900
STEP4_POLL_INTERVAL=15
STEP4_MAX_NEXT=10
```

---

## Usage

```bash
# Normal run (uses STORIES_PER_RUN from .env)
python main.py

# Process only 1 story
python main.py --maxstory 1

# Run headless (no browser window)
python main.py --headless
```

---

## Cookie Login

On the **first run**, the script logs in with your email/password and saves a `cookies.json` file.  
On **every subsequent run**, it loads the saved cookies — no password entry needed.  
If cookies expire, the script detects this automatically, clears the file, and logs in fresh.

---

## Retry Logic

If a story fails mid-way (e.g., render timeout), the script:
1. Saves the **Project URL** (e.g. `https://magiclight.ai/project/edit/123...`) to column N
2. Marks Status as **Pending**

On the next run, it detects the saved URL and jumps **directly to Step 4** — skipping Steps 1–3, saving time and credits.

---

## Local File Structure

Each story creates a named subfolder inside `downloads/`:

```
downloads/
└── Row_2_Luna_and_the_Lantern_of_New_Lights/
    ├── Row_2_Luna_and_the_Lantern_of_New_Lights_thumbnail.jpg
    └── Row_2_Luna_and_the_Lantern_of_New_Lights.mp4
```

The same folder structure is mirrored in Google Drive.

---

## Project Files

```
AutoMagicAI/
├── main.py              # Main automation script
├── credentials.json     # Google Service Account key (DO NOT commit)
├── .env                 # Your configuration (DO NOT commit)
├── .env.example         # Template for .env
├── cookies.json         # Saved login cookies (auto-created, DO NOT commit)
├── .gitignore
├── requirements.txt
├── README.md
└── downloads/           # Video + thumbnail downloads (auto-created)
```

---

## GitHub

Repo: [https://github.com/net2t/AutoMagicAi](https://github.com/net2t/AutoMagicAi)  
Author: **net2t** · net2tara@gmail.com
