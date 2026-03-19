# AutoMagicAI 🎬

Automates AI video generation on [MagicLight.AI](https://magiclight.ai) — reads stories from a Google Sheet, generates **Kids Story Videos**, downloads the video & thumbnail, uploads them to **Google Drive**, and writes results back to the sheet.

---

## Features

- ✅ Reads stories from a Google Sheet
- ✅ Logs in to MagicLight.AI automatically
- ✅ Navigates the full 4-step Kids Story generation flow
- ✅ Selects: Pixar 2.0 style · 16:9 ratio · 1 min · English · GPT-4 · Ethan voice
- ✅ Waits for video render (up to 10 min per story)
- ✅ Downloads video + magic thumbnail
- ✅ Uploads both to Google Drive (per-story subfolder)
- ✅ Updates Google Sheet: Status, Video ID, URLs, Notes, Hashtags
- ✅ Configurable via `.env` — no code changes needed

---

## Google Sheet Format

The script expects a sheet with the following **column headers** in row 1:

| A | B | C | D | E | F | G | H | I | J | K | L | M |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Theme | Title | Story Text | Moral | Hashtags | Date & Time | Status | Word Count | Video ID | YouTube URL | Drive Thumbnail URL | Drive Video URL | Notes |

- The script skips rows where **Status = "Generated"**
- Rows with empty **Story Text** are also skipped

---

## Project Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Google Service Account (for Sheets + Drive access)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** → Download the JSON key → Save as `credentials.json` in this folder
4. Share your Google Sheet and Google Drive folder with the service account email (found inside `credentials.json` under `client_email`)

### 3. Configure `.env`

Copy `.env` and fill in your values:

```ini
SPREADSHEET_ID=your_spreadsheet_id_here
ML_EMAIL=your_magiclight_email@example.com
ML_PASSWORD=your_magiclight_password
STORIES_PER_RUN=2
GOOGLE_DRIVE_FOLDER_ID=your_google_drive_folder_id_here
```

**Where to find IDs:**
- **SPREADSHEET_ID** → The long ID in your Google Sheet URL
- **GOOGLE_DRIVE_FOLDER_ID** → ID at the end of your Google Drive folder URL  
  e.g. `https://drive.google.com/drive/folders/1Abc2Def3Ghi` → ID is `1Abc2Def3Ghi`

---

## Usage

```bash
python main.py
```

A Chromium browser window will open. The script will:
1. Log in to MagicLight.AI
2. Process up to `STORIES_PER_RUN` stories from the sheet
3. Generate videos, download them, and upload to Drive
4. Update the sheet with results

> **Credit usage**: Each story generation costs ~60–100 credits on MagicLight.AI.

---

## File Structure

```
AutoMagicAI/
├── main.py              # Main automation script
├── credentials.json     # Google Service Account key (DO NOT commit)
├── .env                 # Configuration (DO NOT commit)
├── .gitignore
├── requirements.txt
├── README.md
└── downloads/           # Temporary download folder (created at runtime)
```

---

## GitHub

Repo: [https://github.com/net2t/AutoMagicAi](https://github.com/net2t/AutoMagicAi)  
Author: **net2t** · net2tara@gmail.com
