"""
AutoMagicAI — Automated video generation from Google Sheets using MagicLight.AI
Author: net2t (net2tara@gmail.com)
Repo: https://github.com/net2t/AutoMagicAi
"""

import os
import time
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright, Download
from google.oauth2.service_account import Credentials as GACredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# ── Load config from .env ────────────────────────────────────────────────────
load_dotenv()

SPREADSHEET_ID     = os.getenv("SPREADSHEET_ID", "")
ML_EMAIL           = os.getenv("ML_EMAIL", "")
ML_PASSWORD        = os.getenv("ML_PASSWORD", "")
STORIES_PER_RUN    = int(os.getenv("STORIES_PER_RUN", "2"))
DRIVE_FOLDER_ID    = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
CREDS_FILE         = "credentials.json"
DOWNLOADS_DIR      = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# ── Google API Scopes ────────────────────────────────────────────────────────
SHEETS_SCOPES = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/drive"]
DRIVE_SCOPES  = ["https://www.googleapis.com/auth/drive"]

# Column indices (1-based) matching the sheet headers:
# Theme | Title | Story Text | Moral | Hashtags | Date&Time | Status |
# Word Count | Video ID | YouTube URL | Drive Thumbnail URL | Drive Video URL | Notes
COL_STATUS          = 7
COL_VIDEO_ID        = 9
COL_YOUTUBE_URL     = 10
COL_THUMB_URL       = 11
COL_VIDEO_URL       = 12
COL_NOTES           = 13


# ── Google Sheets ─────────────────────────────────────────────────────────────
def get_sheet():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SHEETS_SCOPES)
        client = gspread.authorize(creds)
        return client.open_by_key(SPREADSHEET_ID).sheet1
    except Exception as e:
        print(f"[ERROR] Could not connect to Google Sheets: {e}")
        return None


# ── Google Drive ──────────────────────────────────────────────────────────────
def get_drive_service():
    creds = GACredentials.from_service_account_file(CREDS_FILE, scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


def create_drive_folder(service, name: str, parent_id: str) -> str:
    """Create a subfolder inside parent_id and return its ID."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_to_drive(service, local_path: str, folder_id: str) -> str:
    """Upload a file to Drive and return a shareable link."""
    name = os.path.basename(local_path)
    mime = "video/mp4" if local_path.endswith(".mp4") else "image/jpeg"
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    file_meta = {"name": name, "parents": [folder_id]}
    uploaded = service.files().create(
        body=file_meta, media_body=media, fields="id, webViewLink"
    ).execute()
    # Make publicly readable
    service.permissions().create(
        fileId=uploaded["id"],
        body={"role": "reader", "type": "anyone"},
    ).execute()
    return uploaded.get("webViewLink", "")


# ── Login ─────────────────────────────────────────────────────────────────────
def login(page):
    print("[Login] Navigating to login page...")
    page.goto("https://magiclight.ai/login/", timeout=60000)
    time.sleep(4)

    # Already logged in?
    if "login" not in page.url.lower():
        print("[Login] Already logged in — skipping.")
        return

    # Step 1: click "Log in with Email"
    email_option = page.locator("text='Log in with Email'")
    if email_option.count() > 0:
        print("[Login] Clicking 'Log in with Email'...")
        email_option.first.click()
        time.sleep(3)

    # Step 2: fill email (field is type="text" on this site)
    print("[Login] Filling email...")
    email_input = page.locator('input[type="text"], input[type="email"]')
    email_input.first.wait_for(state="visible", timeout=10000)
    email_input.first.fill(ML_EMAIL)
    time.sleep(0.5)

    # Step 3: fill password
    print("[Login] Filling password...")
    pwd_input = page.locator('input[type="password"]')
    pwd_input.first.wait_for(state="visible", timeout=10000)
    pwd_input.first.fill(ML_PASSWORD)
    time.sleep(0.5)

    # Step 4: click the "Continue" button (gradient button visible in screenshot)
    print("[Login] Clicking Continue button...")
    continue_btn = page.locator("button:has-text('Continue')")
    if continue_btn.count() == 0:
        continue_btn = page.locator("button").filter(has_text="Continue")
    continue_btn.first.wait_for(state="visible", timeout=10000)
    continue_btn.first.click()

    # Step 5: wait for dashboard to load
    print("[Login] Waiting for dashboard...")
    try:
        page.wait_for_url("**/home/**", timeout=30000)
    except Exception:
        try:
            page.wait_for_url("**/dashboard**", timeout=10000)
        except Exception:
            pass
    time.sleep(3)

    if "login" in page.url.lower():
        raise Exception("Login failed — still on login page after Continue click.")

    print(f"[Login] Success! Current URL: {page.url}")


# ── Dismiss any popups / modals ───────────────────────────────────────────────
def dismiss_popups(page):
    time.sleep(1)
    for selector in [
        "button:has-text('OK')",
        "button:has-text('Got it')",
        "button:has-text('Close')",
        ".arco-modal-close-btn",
        ".sora2-modal .close",
        "[aria-label='Close']",
        "button:has-text('×')",
    ]:
        try:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(0.5)
        except Exception:
            pass


# ── Step 1: Content — fill story and settings ─────────────────────────────────
def step1_content(page, story_text: str):
    print("[Step 1] Navigating to Kids Story page...")
    page.goto("https://magiclight.ai/kids-story/", timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(5)
    dismiss_popups(page)

    # Story Topic textarea
    print("[Step 1] Entering story text...")
    textarea = page.locator("textarea[placeholder*='original story']")
    textarea.wait_for(state="visible", timeout=20000)
    textarea.fill(story_text)
    time.sleep(1)

    # Style: Pixar 2.0
    print("[Step 1] Selecting Pixar 2.0 style...")
    try:
        pixar_option = page.locator("text='Pixar 2.0'")
        if pixar_option.count() > 0:
            pixar_option.first.click()
            time.sleep(1)
    except Exception:
        print("[Step 1] Pixar 2.0 not found, using default style")

    # Aspect Ratio: 16:9 (default, but explicitly set)
    try:
        ratio_btn = page.locator("button:has-text('16:9'), div:has-text('16:9')").first
        if ratio_btn.is_visible():
            ratio_btn.click()
            time.sleep(0.5)
    except Exception:
        pass

    # Video Duration: 1min (default)
    # Language: English (default)
    # Story Model: GPT-4, Voiceover: Ethan, Background Music: Rosita
    # These are usually dropdowns — try to set them:
    try:
        _set_dropdown(page, "Story Model", "GPT-4")
    except Exception:
        pass
    try:
        _set_dropdown(page, "Voiceover", "Ethan")
    except Exception:
        pass
    try:
        _set_dropdown(page, "Background Music", "Rosita")
    except Exception:
        pass

    # Click Next
    print("[Step 1] Clicking Next...")
    _click_next(page)


def _set_dropdown(page, label: str, value: str):
    """Find a dropdown by its visible label text and select a value."""
    label_el = page.locator(f"text='{label}'").first
    if label_el.is_visible():
        # Click on the dropdown arrow/container near the label
        parent = label_el.locator("xpath=ancestor::*[contains(@class,'select') or contains(@class,'dropdown')][1]")
        if parent.count() > 0:
            parent.first.click()
            time.sleep(1)
            option = page.locator(f"text='{value}'")
            if option.count() > 0 and option.first.is_visible():
                option.first.click()
                time.sleep(0.5)


def _click_next(page):
    """Click the Next or Next Step button, retrying if needed."""
    for attempt in range(5):
        for sel in [
            "button:has-text('Next')",
            "div.page-footer button:has-text('Next')",
            "[class*='next-btn']",
            "span:has-text('Next')",
        ]:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                try:
                    btn.first.click(timeout=5000)
                    time.sleep(3)
                    return
                except Exception:
                    pass
        time.sleep(2)
    raise Exception("Could not find or click the Next button")


# ── Step 2: Cast — auto-selected, just click Next Step ───────────────────────
def step2_cast(page):
    print("[Step 2] Cast — waiting for characters to load...")
    time.sleep(8)
    dismiss_popups(page)

    # Click "Next Step" (costs ~60 credits)
    print("[Step 2] Clicking Next Step...")
    next_step_btn = page.locator("button:has-text('Next Step')")
    next_step_btn.wait_for(state="visible", timeout=30000)
    next_step_btn.first.click()
    time.sleep(5)


# ── Step 3: Storyboard — wait for images + click Next ────────────────────────
def step3_storyboard(page):
    print("[Step 3] Storyboard — waiting for AI to generate images...")
    dismiss_popups(page)
    timeout = 120  # seconds to wait for storyboards
    start = time.time()
    while time.time() - start < timeout:
        # Check for storyboard thumbnails in the sidebar
        boards = page.locator("[class*='storyboard'] img, .scene-list img, [class*='scene'] img")
        if boards.count() >= 2:
            print(f"[Step 3] Storyboards ready ({boards.count()} detected).")
            break
        time.sleep(5)
    else:
        print("[Step 3] Timeout waiting for storyboards — proceeding anyway.")

    time.sleep(3)
    # Click Next (top-right corner)
    print("[Step 3] Clicking Next (top-right)...")
    for sel in ["button:has-text('Next')", "[class*='next-btn']", "button.btn-primary:has-text('Next')"]:
        btn = page.locator(sel)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            time.sleep(5)
            return
    raise Exception("Storyboard Next button not found")


# ── Step 4: Edit — click Generate, confirm popup, wait for render ─────────────
def step4_edit_and_generate(page) -> tuple[str, str, str, str]:
    """
    Clicks Generate, waits for video render, extracts title, thumbnail_url,
    video_url, hashtags. Returns (video_id, title, thumbnail_url, hashtags).
    """
    print("[Step 4] Edit — clicking Generate...")
    dismiss_popups(page)
    time.sleep(3)

    gen_btn = page.locator("button:has-text('Generate')")
    gen_btn.wait_for(state="visible", timeout=30000)
    gen_btn.first.click()
    time.sleep(3)

    # Export popup: 16:9 and Standard (720p) are defaults — click OK
    print("[Step 4] Confirming export settings...")
    ok_btn = page.locator("button:has-text('OK')")
    if ok_btn.count() > 0 and ok_btn.first.is_visible():
        ok_btn.first.click()
    time.sleep(3)
    dismiss_popups(page)

    # Wait for render to finish. Look for download button or success popup.
    print("[Step 4] Waiting for video render (up to 10 min)...")
    start = time.time()
    while time.time() - start < 600:
        # Check for the success popup "Your work ... video has been generated"
        success = page.locator("text='video has been generated'")
        if success.count() > 0 and success.first.is_visible():
            print("[Step 4] Success popup detected!")
            break
        # Also check for download button
        dl = page.locator("button:has-text('Download'), a:has-text('Download')")
        if dl.count() > 0 and dl.first.is_visible():
            print("[Step 4] Download button detected!")
            break
        time.sleep(10)
        print(f"[Step 4] Still rendering... ({int(time.time()-start)}s elapsed)")

    # Dismiss the "generated" popup (click X)
    time.sleep(2)
    for sel in [
        "button:has-text('×')",
        "button[aria-label='Close']",
        ".arco-modal-close-btn",
        ".popup-close",
        "[class*='close']",
    ]:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                break
        except Exception:
            pass

    # Extract video ID from URL
    video_id = page.url.strip("/").split("/")[-1]
    if not video_id or video_id in ["edit", "project"]:
        video_id = "unknown_" + str(int(time.time()))

    # Extract title from page
    title = ""
    try:
        title_el = page.locator("h1, .project-title, input[type='text'][value]").first
        title = title_el.text_content() or title_el.get_attribute("value") or ""
        title = title.strip()
    except Exception:
        pass

    # Extract thumbnail image URL (the "Magic Thumbnail")
    thumb_url = ""
    try:
        thumb = page.locator("[class*='thumbnail'] img, [class*='cover'] img").first
        thumb_url = thumb.get_attribute("src") or ""
    except Exception:
        pass

    # Extract hashtags if visible on the page
    hashtags = ""
    try:
        tag_el = page.locator("[class*='hashtag'], [class*='tag']")
        tags = [t.text_content().strip() for t in tag_el.all() if t.text_content()]
        hashtags = " ".join(tags)
    except Exception:
        pass

    print(f"[Step 4] Video ID: {video_id}, Title: {title!r}")
    return video_id, title, thumb_url, hashtags


# ── Download video via Playwright Download event ──────────────────────────────
def download_video(page, row_label: str) -> str:
    """Click the Download button and save the video. Returns local path."""
    print(f"[Download] Looking for video download button...")
    dl_btn = page.locator("button:has-text('Download'), a:has-text('Download')")
    if dl_btn.count() == 0:
        print("[Download] No download button found.")
        return ""
    try:
        with page.expect_download(timeout=120000) as dl_info:
            dl_btn.first.click()
        download: Download = dl_info.value
        dest = os.path.join(DOWNLOADS_DIR, f"{row_label}_{download.suggested_filename or 'video.mp4'}")
        download.save_as(dest)
        print(f"[Download] Video saved to: {dest}")
        return dest
    except Exception as e:
        print(f"[Download] Video download failed: {e}")
        return ""


def download_thumbnail(thumb_url: str, row_label: str) -> str:
    """Download thumbnail image from URL. Returns local path."""
    if not thumb_url:
        return ""
    try:
        resp = requests.get(thumb_url, timeout=30)
        ext = ".jpg" if "jpg" in thumb_url.lower() else ".png"
        dest = os.path.join(DOWNLOADS_DIR, f"{row_label}_thumb{ext}")
        with open(dest, "wb") as f:
            f.write(resp.content)
        print(f"[Download] Thumbnail saved to: {dest}")
        return dest
    except Exception as e:
        print(f"[Download] Thumbnail download failed: {e}")
        return ""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  AutoMagicAI — MagicLight.AI Automation")
    print("=" * 60)

    # Validate config
    if not SPREADSHEET_ID:
        print("[ERROR] SPREADSHEET_ID not set in .env")
        return
    if not ML_EMAIL or not ML_PASSWORD:
        print("[ERROR] ML_EMAIL / ML_PASSWORD not set in .env")
        return

    # Connect to Google Sheet
    print("[Setup] Connecting to Google Sheets...")
    sheet = get_sheet()
    if not sheet:
        return

    records = sheet.get_all_records()
    print(f"[Setup] Found {len(records)} rows in sheet.")

    # Connect to Google Drive if folder ID is set
    drive_service = None
    if DRIVE_FOLDER_ID:
        print("[Setup] Connecting to Google Drive...")
        try:
            drive_service = get_drive_service()
            print("[Setup] Google Drive connected.")
        except Exception as e:
            print(f"[Setup] Drive connection failed (will skip upload): {e}")
    else:
        print("[Setup] GOOGLE_DRIVE_FOLDER_ID not set — Drive upload disabled.")

    # Launch browser
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # Login
        try:
            login(page)
        except Exception as e:
            print(f"[FATAL] Login failed: {e}")
            browser.close()
            return

        processed = 0

        for idx, row in enumerate(records, start=2):
            if processed >= STORIES_PER_RUN:
                print(f"\n[Limit] Reached {STORIES_PER_RUN} stories for this run. Stopping.")
                break

            # Skip already-generated rows
            if row.get("Status", "").strip().lower() == "generated":
                continue

            story = row.get("Story Text", "").strip()
            if not story:
                continue

            title_hint = row.get("Title", f"Row_{idx}")
            moral = row.get("Moral", "").strip()
            row_label = f"row{idx}_{title_hint[:30].replace(' ', '_')}"

            prompt = story
            if moral:
                prompt += f"\n\nMoral of the story: {moral}"

            print(f"\n{'='*60}")
            print(f"[Processing] Row {idx}: {title_hint}")
            print(f"{'='*60}")

            try:
                # ── Generation Pipeline ────────────────────────────────────
                step1_content(page, prompt)
                step2_cast(page)
                step3_storyboard(page)
                video_id, gen_title, thumb_url, hashtags = step4_edit_and_generate(page)

                # Use generated title or fallback to sheet title
                final_title = gen_title or title_hint

                # ── Downloads ─────────────────────────────────────────────
                video_local = download_video(page, row_label)
                thumb_local = download_thumbnail(thumb_url, row_label)

                # ── Drive Upload ──────────────────────────────────────────
                drive_video_url = ""
                drive_thumb_url = ""
                if drive_service and DRIVE_FOLDER_ID:
                    try:
                        sub_folder_id = create_drive_folder(
                            drive_service,
                            f"Row_{idx}_{final_title[:40]}",
                            DRIVE_FOLDER_ID,
                        )
                        if video_local and os.path.exists(video_local):
                            drive_video_url = upload_to_drive(drive_service, video_local, sub_folder_id)
                            print(f"[Drive] Video uploaded → {drive_video_url}")
                        if thumb_local and os.path.exists(thumb_local):
                            drive_thumb_url = upload_to_drive(drive_service, thumb_local, sub_folder_id)
                            print(f"[Drive] Thumbnail uploaded → {drive_thumb_url}")
                    except Exception as e:
                        print(f"[Drive] Upload error: {e}")

                # ── Update Google Sheet ────────────────────────────────────
                notes = f"Title: {final_title} | Hashtags: {hashtags}".strip(" |")
                sheet.update_cell(idx, COL_STATUS,    "Generated")
                sheet.update_cell(idx, COL_VIDEO_ID,  video_id)
                sheet.update_cell(idx, COL_THUMB_URL, drive_thumb_url or thumb_url)
                sheet.update_cell(idx, COL_VIDEO_URL, drive_video_url)
                sheet.update_cell(idx, COL_NOTES,     notes)

                print(f"[Sheet] Row {idx} updated ✓")
                processed += 1

            except Exception as e:
                print(f"[ERROR] Row {idx} failed: {e}")
                try:
                    sheet.update_cell(idx, COL_STATUS, "Error")
                    sheet.update_cell(idx, COL_NOTES,  str(e)[:500])
                except Exception:
                    pass

        print(f"\n[Done] Processed {processed} stories.")
        browser.close()


if __name__ == "__main__":
    main()
