"""
AutoMagicAI — Automated video generation from Google Sheets using MagicLight.AI
Author: net2t (net2tara@gmail.com)
Repo: https://github.com/net2t/AutoMagicAi
"""

import os
import sys
import time
import signal
import argparse
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright, Download
from google.oauth2.service_account import Credentials as GACredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# ── Load config from .env ─────────────────────────────────────────────────────
load_dotenv()

# Global variables for graceful shutdown
shutdown_requested = False
browser_instance = None

SPREADSHEET_ID  = os.getenv("SPREADSHEET_ID", "")
ML_EMAIL        = os.getenv("ML_EMAIL", "")
ML_PASSWORD     = os.getenv("ML_PASSWORD", "")
STORIES_PER_RUN = int(os.getenv("STORIES_PER_RUN", "2"))
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
CREDS_FILE      = "credentials.json"
DOWNLOADS_DIR   = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Google API scopes
SHEETS_SCOPES = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/drive"]
DRIVE_SCOPES  = ["https://www.googleapis.com/auth/drive"]

# Sheet column indices (1-based):
# Theme|Title|Story Text|Moral|Hashtags|Date&Time|Status|WordCount|VideoID|YouTubeURL|DriveThumbURL|DriveVideoURL|Notes
COL_STATUS    = 7
COL_VIDEO_ID  = 9
COL_YOUTUBE   = 10
COL_THUMB_URL = 11
COL_VIDEO_URL = 12
COL_NOTES     = 13

# ── Graceful Shutdown Handler ───────────────────────────────────────────────────
def signal_handler(signum, frame):
    """Handle CTRL+C signal gracefully."""
    global shutdown_requested, browser_instance
    print("\n\n[GRACEFUL SHUTDOWN] CTRL+C detected. Cleaning up...")
    shutdown_requested = True
    
    if browser_instance:
        print("[GRACEFUL SHUTDOWN] Closing browser...")
        try:
            browser_instance.close()
        except Exception as e:
            print(f"[GRACEFUL SHUTDOWN] Error closing browser: {e}")
    
    print("[GRACEFUL SHUTDOWN] Cleanup complete. Exiting...")
    sys.exit(0)

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)

# ── CLI Arguments ─────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="AutoMagicAI — Kids Story video generator")
    parser.add_argument(
        "--maxstory", "-n",
        type=int,
        default=None,
        help="Number of stories to process in this run (overrides .env STORIES_PER_RUN)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run browser in headless mode (no visible window)"
    )
    return parser.parse_args()


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
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_to_drive(service, local_path: str, folder_id: str) -> str:
    name = os.path.basename(local_path)
    mime = "video/mp4" if local_path.endswith(".mp4") else "image/jpeg"
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    file_meta = {"name": name, "parents": [folder_id]}
    uploaded = service.files().create(
        body=file_meta, media_body=media, fields="id, webViewLink"
    ).execute()
    service.permissions().create(
        fileId=uploaded["id"],
        body={"role": "reader", "type": "anyone"},
    ).execute()
    return uploaded.get("webViewLink", "")


# ── Login ─────────────────────────────────────────────────────────────────────
def login(page):
    print("[Login] Navigating to login page...")
    page.goto("https://magiclight.ai/login/", timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(4)

    # Already logged in?
    if "login" not in page.url.lower():
        print("[Login] Already logged in — skipping.")
        return

    # Click "Sign in with Email" or "Log in with Email" (a <div class="entry-email">)
    print("[Login] Clicking 'Sign in with Email'...")
    email_entry = None
    deadline = time.time() + 15
    while time.time() < deadline:
        for sel in [
            "div.entry-email",
            "text='Sign in with Email'",
            "text='Log in with Email'",
            ".login-methods div"
        ]:
            try:
                el = page.locator(sel)
                if el.count() > 0 and el.first.is_visible():
                    email_entry = el.first
                    break
            except Exception:
                pass
        if email_entry:
            break
        time.sleep(1)
        
    if email_entry is None:
        raise Exception("Could not find 'Sign in with Email' option on login page.")
        
    try:
        email_entry.click()
    except Exception:
        email_entry.first.click()
    time.sleep(3)

    # Fill Email (input type="text" on this site)
    print("[Login] Filling email...")
    email_input = page.locator('input[type="text"], input[type="email"]')
    email_input.first.wait_for(state="visible", timeout=10000)
    email_input.first.click()
    email_input.first.fill(ML_EMAIL)
    time.sleep(0.5)

    # Fill Password
    print("[Login] Filling password...")
    pwd_input = page.locator('input[type="password"]')
    pwd_input.first.wait_for(state="visible", timeout=10000)
    pwd_input.first.click()
    pwd_input.first.fill(ML_PASSWORD)
    time.sleep(0.5)

    # Click Continue — it's a <div class="signin-continue">, NOT a <button>
    print("[Login] Clicking Continue (div.signin-continue)...")
    continue_el = page.locator("div.signin-continue")
    if continue_el.count() == 0:
        # broad fallback
        continue_el = page.locator("text='Continue'")
    continue_el.first.wait_for(state="visible", timeout=10000)
    continue_el.first.click()

    # Wait for redirect away from login
    print("[Login] Waiting for dashboard...")
    try:
        page.wait_for_url("**/home**", timeout=30000)
    except Exception:
        time.sleep(8)

    if "login" in page.url.lower():
        raise Exception("Login failed — still on login page after clicking Continue.")

    print(f"[Login] ✓ Success! URL: {page.url}")


# ── Utility ───────────────────────────────────────────────────────────────────
def dismiss_popups(page):
    """Silently close any modal/popup that might be in the way."""
    for selector in [
        ".arco-modal-close-btn",
        "button:has-text('OK')",
        "button:has-text('Got it')",
        "button:has-text('Close')",
        "[aria-label='Close']",
        ".sora2-modal .close",
        ".notice-popup-modal__close",
    ]:
        try:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(0.5)
        except Exception:
            pass


def _dismiss_animation_modal(page):
    """Dismiss the 'Animate All' suggestion modal that appears after each Next click.
    Clicks the secondary 'Next' button (arco-btn-secondary) inside the modal to skip animation."""
    js = """
    () => {
        // The animation modal dismiss button is BUTTON.arco-btn-secondary with text 'Next' or 'Skip'
        const btns = Array.from(document.querySelectorAll('button.arco-btn-secondary, .arco-modal-footer button'));
        for (const el of btns) {
            const t = (el.innerText || '').trim();
            const rect = el.getBoundingClientRect();
            if ((t === 'Next' || t === 'Skip') && rect.width > 0 && rect.height > 0) {
                el.click();
                return 'Dismissed modal via arco-btn-secondary: ' + t;
            }
        }
        return null;
    }
    """
    try:
        result = page.evaluate(js)
        if result:
            print(f"[Modal] ✓ {result}")
            time.sleep(2)
    except Exception:
        pass


def _click_next(page, timeout=20000):
    """Robustly click any 'Next' button visible on the current page."""
    # Specific selector to avoid the 'Next' button *inside* the tutorial popup 
    # (assuming tutorial is dismissed, but this provides extra safety)
    selectors = [
        "button.arco-btn-primary:has-text('Next')",
        "button:has-text('Next')",
        "div.page-footer button",
        "[class*='next-btn']",
        "div:has-text('Next') >> visible=true",
        "span:has-text('Next')",
    ]
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                btn = page.locator(sel).last  # Use last() to target the main page button, usually at the bottom
                if btn.is_visible():
                    btn.click()
                    time.sleep(3)
                    return
            except Exception:
                pass
        time.sleep(2)
    raise Exception("Could not find a clickable Next button")


def _set_dropdown_value(page, label_text: str, value_text: str):
    """Find a labeled dropdown and select a value from it."""
    try:
        # Find the label, then locate the associated select/dropdown container
        label = page.locator(f"text='{label_text}'").first
        if not label.is_visible():
            return
        # Click the closest arco-select
        container = page.locator(f"text='{label_text}' >> xpath=following-sibling::*[1]//div[contains(@class,'select')]")
        if container.count() > 0:
            container.first.click()
            time.sleep(1)
            option = page.locator(f".arco-select-dropdown li:has-text('{value_text}'), li:has-text('{value_text}')")
            if option.count() > 0 and option.first.is_visible():
                option.first.click()
                time.sleep(0.5)
    except Exception:
        pass


# ── Step 1: Content ───────────────────────────────────────────────────────────
def _dismiss_tour(page):
    """Dismiss the on-boarding tour overlay (diy-tour) if present via JS."""
    try:
        # Wait a moment for any tours to pop up
        time.sleep(3)
        print("[Tour] Checking for tutorial overlays...")
        
        # 1. Use JS to natively click any button/span/div with exact text "Skip", "Got it", or "Close"
        # We run it a few times in case the tour has multiple steps (e.g., 1/2 -> 2/2)
        js_click = """
        () => {
            const texts = ["Skip", "Got it", "Got It", "Close", "Done"];
            document.querySelectorAll('button, span, div, a').forEach(el => {
                if (el.innerText && texts.includes(el.innerText.trim())) {
                    el.click();
                }
            });
        }
        """
        for _ in range(3):
            page.evaluate(js_click)
            time.sleep(1)
            
        # 2. Force remove the tour DOM elements just in case they're still blocking
        js_remove = """
        () => {
            document.querySelectorAll('.diy-tour, .diy-tour__mask, [class*="tour-tooltip"], [class*="driver-"]').forEach(el => {
                try { el.remove(); } catch(e) {}
            });
        }
        """
        page.evaluate(js_remove)
        time.sleep(1)
        
    except Exception as e:
        print(f"[Tour] Error during tour dismissal: {e}")


# ── Step 1: Content ───────────────────────────────────────────────────────────
def step1_content(page, story_text: str):
    print("[Step 1] Navigating to Kids Story page...")
    page.goto("https://magiclight.ai/kids-story/", timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(6)
    dismiss_popups(page)
    _dismiss_tour(page)

    # Paste story into the Story Topic textarea
    print("[Step 1] Pasting story text...")
    textarea = page.locator("textarea[placeholder*='original story']")
    textarea.wait_for(state="visible", timeout=20000)

    # Use JS fill to bypass any remaining overlay / z-index issues
    textarea.first.evaluate(f"el => {{ el.value = {repr(story_text)}; el.dispatchEvent(new Event('input', {{bubbles:true}})); }}")
    time.sleep(1)

    # Style: Pixar 2.0
    print("[Step 1] Selecting Pixar 2.0 style...")
    try:
        pixar = page.locator("text='Pixar 2.0'")
        if pixar.count() > 0 and pixar.first.is_visible():
            pixar.first.click()
            time.sleep(1)
    except Exception:
        print("[Step 1] Pixar 2.0 not clickable, skipping")

    # Aspect Ratio: 16:9 (click to ensure it's selected)
    try:
        r169 = page.locator("text='16:9'")
        if r169.count() > 0 and r169.first.is_visible():
            r169.first.click()
    except Exception:
        pass

    # Dropdowns: Video Duration=1min, Language=English, Story Model=GPT-4, Voiceover=Ethan, BGM=Rosita
    # These are already the defaults — only change if they appear non-default
    # (skip silent failures to avoid breaking the flow)
    _set_dropdown_value(page, "Video Duration", "1min")
    _set_dropdown_value(page, "Language", "English")
    _set_dropdown_value(page, "Story Model", "GPT-4")
    _set_dropdown_value(page, "Voiceover", "Ethan")
    _set_dropdown_value(page, "Background Music", "Rosita")

    time.sleep(1)

    # Scroll down to make Next visible and click it
    print("[Step 1] Clicking Next...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)
    _click_next(page)


# ── Step 2: Cast ──────────────────────────────────────────────────────────────
def _dom_click_text(page, texts: list, timeout: int = 120) -> bool:
    """Click the last visible button-like element whose DIRECT text node matches any of 'texts'.
    Uses firstChild.textContent to avoid matching credit-badge children like 'Next Step\\n60'.
    Returns True if clicked, False if timed out."""
    js = """
    (texts) => {
        const all = Array.from(document.querySelectorAll(
            'button, div[class*="btn"], span[class*="btn"], a, div[class*="vlog-btn"], div[class*="footer-btn"]'
        ));
        // Iterate in reverse so the bottom-most (primary action) element wins
        for (let i = all.length - 1; i >= 0; i--) {
            const el = all[i];
            // Use direct text node only (not innerText) to avoid child badge text
            let directText = '';
            el.childNodes.forEach(n => {
                if (n.nodeType === Node.TEXT_NODE) directText += n.textContent;
            });
            directText = directText.trim();
            // Fallback to innerText if no direct text node
            const fullText = (el.innerText || '').trim();
            const t = directText || fullText;
            if (texts.includes(t)) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    el.click();
                    return t;
                }
            }
        }
        return null;
    }
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = page.evaluate(js, texts)
        if result:
            print(f"[DOM] ✓ Clicked '{result}'")
            return True
        time.sleep(3)
    return False


def _dom_click_class(page, css_class: str, timeout: int = 30) -> bool:
    """Click a visible element by exact CSS class substring. More reliable when text contains child nodes."""
    js = f"""
    () => {{
        const all = Array.from(document.querySelectorAll('[class*="{css_class}"]'));
        for (let i = all.length - 1; i >= 0; i--) {{
            const el = all[i];
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {{
                el.click();
                return el.className;
            }}
        }}
        return null;
    }}
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = page.evaluate(js)
        if result:
            print(f"[DOM] ✓ Clicked class ~'{css_class}' -> '{result}'")
            return True
        time.sleep(3)
    return False


def _dom_debug_buttons(page):
    """Print all visible clickable elements for debugging."""
    js = """
    () => {
        const all = Array.from(document.querySelectorAll(
            'button, div[class*="btn"], span[class*="btn"], a, div[class*="vlog-btn"]'
        ));
        const results = [];
        all.forEach(el => {
            const t = (el.innerText || '').trim().substring(0, 60);
            const rect = el.getBoundingClientRect();
            if (t && rect.width > 0 && rect.height > 0) {
                results.push(el.tagName + '.' + (el.className||'').substring(0,40) + ' | ' + t);
            }
        });
        return results;
    }
    """
    try:
        items = page.evaluate(js)
        print(f"[DEBUG] URL: {page.url}")
        print(f"[DEBUG] Visible buttons/links:")
        for item in (items or []):
            print(f"  {item}")
    except Exception as e:
        print(f"[DEBUG] Could not dump buttons: {e}")


def step2_cast(page):
    print("[Step 2] Cast — waiting for characters to analyze and generate...")
    time.sleep(10)
    dismiss_popups(page)

    # Primary: Click 'Next Step' by class (step2-footer-btn-left)
    # (innerText is 'Next Step\n60' due to credits badge child, so class-based is more reliable)
    print("[Step 2] Clicking Next Step via class (step2-footer-btn-left)...")
    if _dom_click_class(page, "step2-footer-btn-left", timeout=120):
        print("[Step 2] ✓ Done.")
    else:
        # Fallback: try text-based
        if _dom_click_text(page, ["Next Step", "Animate All", "Create now"], timeout=30):
            print("[Step 2] ✓ Done (fallback text match).")
        else:
            _dom_debug_buttons(page)
            print("[Step 2] Could not find Next Step button — assuming auto-skipped.")
    time.sleep(4)
    _dismiss_animation_modal(page)  # Dismiss animation suggestion modal
    time.sleep(4)


# ── Step 3: Storyboard ────────────────────────────────────────────────────────
def step3_storyboard(page):
    print("[Step 3] Storyboard — waiting for AI to generate images (up to 3 min)...")
    dismiss_popups(page)

    # Wait for storyboard/role-card images to appear (any img inside the edit page content)
    js_count = """
    () => {
        // MagicLight storyboard images appear inside role-card or video-scene elements
        const imgs = document.querySelectorAll('[class*="role-card"] img, [class*="scene"] img, [class*="storyboard"] img, [class*="story-board"] img, [class*="video-scene"] img, [class*="frame"] img');
        return imgs.length;
    }
    """
    deadline = time.time() + 180
    while time.time() < deadline:
        count = page.evaluate(js_count)
        if count >= 2:
            print(f"[Step 3] ✓ Storyboard images ready ({count} found)")
            break
        time.sleep(5)
        print(f"[Step 3] Waiting for storyboard images... ({int(deadline - time.time())}s left)")
    else:
        print("[Step 3] Timeout — proceeding anyway")

    time.sleep(3)

    # Click Next Step by class to proceed to Storyboard edit
    print("[Step 3] Clicking Next Step via class (step2-footer-btn-left)...")
    if _dom_click_class(page, "step2-footer-btn-left", timeout=20):
        print("[Step 3] ✓ Done.")
        time.sleep(4)
        _dismiss_animation_modal(page)  # Dismiss animation modal
        time.sleep(4)
    else:
        # Fallback text
        if _dom_click_text(page, ["Next", "Next Step", "Create now"], timeout=15):
            print("[Step 3] ✓ Done (fallback).")
            time.sleep(4)
            _dismiss_animation_modal(page)
            time.sleep(4)
        else:
            _dom_debug_buttons(page)
            print("[Step 3] Next button not found — proceeding to Step 4.")

# ── Step 4: Edit → Generate → Wait → Download ────────────────────────────────
def step4_generate_and_download(page, row_label: str) -> dict:
    """
    Clicks Generate via DOM, confirms export popup, waits for render,
    downloads video and thumbnail. Returns a dict with all extracted data.
    """
    print("[Step 4] Edit — navigating sub-steps to reach Generate screen...")
    dismiss_popups(page)
    time.sleep(3)

    generate_texts = ["Generate", "Create Video", "Export", "Create now", "Render"]
    max_next_clicks = 6
    for attempt in range(max_next_clicks):
        js_has_generate = """
        (texts) => {
            const all = Array.from(document.querySelectorAll(
                'button, div[class*="btn"], span[class*="btn"], div[class*="footer-btn"]'
            ));
            for (let i = all.length - 1; i >= 0; i--) {
                const el = all[i];
                let directText = '';
                el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) directText += n.textContent; });
                const t = (directText.trim() || (el.innerText || '').trim());
                if (texts.includes(t)) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) return t;
                }
            }
            return null;
        }
        """
        found = page.evaluate(js_has_generate, generate_texts)
        if found:
            print(f"[Step 4] ✓ Found '{found}' button — ready to generate!")
            break

        print(f"[Step 4] Generate not yet visible (attempt {attempt+1}/{max_next_clicks}) — clicking Next...")
        js_click_primary_next = """
        () => {
            const primaryBtns = Array.from(document.querySelectorAll('button.arco-btn-primary'));
            for (const el of primaryBtns) {
                const t = (el.innerText || '').trim();
                const rect = el.getBoundingClientRect();
                if (t === 'Next' && rect.width > 0 && rect.height > 0) {
                    el.click();
                    return 'Clicked arco-btn-primary Next';
                }
            }
            const allBtns = Array.from(document.querySelectorAll('button'));
            for (const el of allBtns) {
                const t = (el.innerText || '').trim();
                const rect = el.getBoundingClientRect();
                if (t === 'Next' && rect.width > 0 && rect.height > 0) {
                    el.click();
                    return 'Clicked button Next (fallback)';
                }
            }
            const divs = Array.from(document.querySelectorAll('[class*="header-shiny-action__btn"]'));
            for (const el of divs) {
                const t = (el.innerText || '').trim();
                const rect = el.getBoundingClientRect();
                if (t === 'Next' && rect.width > 0 && rect.height > 0) {
                    el.click();
                    return 'Clicked header div Next';
                }
            }
            return null;
        }
        """
        result = page.evaluate(js_click_primary_next)
        if result:
            print(f"[Step 4] ✓ {result}")
        else:
            print("[Step 4] No Next button found at all")
            _dom_debug_buttons(page)
        time.sleep(3)
        _dismiss_animation_modal(page)
        time.sleep(3)
        dismiss_popups(page)
    else:
        _dom_debug_buttons(page)
        raise Exception("[Step 4] Could not reach Generate screen after max Next clicks")

    # Click Generate
    print("[Step 4] Clicking Generate...")
    if not _dom_click_text(page, generate_texts, timeout=20):
        _dom_debug_buttons(page)
        raise Exception("[Step 4] Generate button found but click failed")
    time.sleep(3)

    # Export popup — click OK via DOM
    print("[Step 4] Confirming export settings (OK) via DOM...")
    _dom_click_text(page, ["OK", "Ok", "Confirm"], timeout=10)
    time.sleep(3)
    dismiss_popups(page)

    # ── Wait for render ───────────────────────────────────────────────────────
    # ✅ FIX: Increased total wait from 600s → 900s (15 minutes)
    # ✅ FIX: Poll every 15s instead of 10s to reduce false negatives
    # ✅ FIX: Added more completion selectors (progress bar, done text, etc.)
    # ✅ FIX: Added clear progress log every 30s so you can see it's alive
    RENDER_TIMEOUT = 900      # 15 minutes total wait
    POLL_INTERVAL  = 15       # check every 15 seconds
    PROGRESS_EVERY = 30       # print status every 30 seconds

    print(f"[Step 4] Waiting for video render (up to {RENDER_TIMEOUT // 60} min)...")
    print("[Step 4] ⏳ Please be patient — MagicLight can take 5–10 minutes...")

    start = time.time()
    last_progress_print = start

    while time.time() - start < RENDER_TIMEOUT:
        elapsed = int(time.time() - start)

        # ── Check 1: Success popup text ──
        for success_text in [
            "video has been generated",
            "Video generated",
            "generation complete",
            "successfully generated",
            "video is ready",
            "Your video is ready",
        ]:
            try:
                if page.locator(f"text='{success_text}'").count() > 0:
                    print(f"[Step 4] ✓ SUCCESS detected: '{success_text}' ({elapsed}s)")
                    time.sleep(5)   # ✅ FIX: buffer for page to fully settle
                    break
            except Exception:
                pass
        else:
            # ── Check 2: Download button visible ──
            try:
                dl_visible = page.locator(
                    "button:has-text('Download'), "
                    "a:has-text('Download'), "
                    "[class*='download-btn'], "
                    "[class*='download_btn']"
                )
                if dl_visible.count() > 0 and dl_visible.first.is_visible():
                    print(f"[Step 4] ✓ Download button appeared! ({elapsed}s)")
                    time.sleep(5)   # ✅ FIX: buffer for page to fully settle
                    break
            except Exception:
                pass

            # ── Check 3: Progress bar gone (render complete indicator) ──
            try:
                progress_bar = page.locator(
                    "[class*='progress-bar'], "
                    "[class*='generating'], "
                    "[class*='render-progress']"
                )
                if progress_bar.count() == 0:
                    # Only treat as done if we've waited at least 60 seconds
                    # (to avoid false positive at the very start)
                    if elapsed > 60:
                        print(f"[Step 4] ✓ Progress bar gone — render likely complete ({elapsed}s)")
                        time.sleep(5)
                        break
            except Exception:
                pass

            # ── Print progress every 30 seconds ──
            if time.time() - last_progress_print >= PROGRESS_EVERY:
                mins  = elapsed // 60
                secs  = elapsed % 60
                remaining = RENDER_TIMEOUT - elapsed
                print(f"[Step 4] ⏳ Still rendering... {mins}m {secs}s elapsed | "
                      f"{remaining // 60}m {remaining % 60}s remaining")
                last_progress_print = time.time()

            time.sleep(POLL_INTERVAL)

    else:
        # Timeout reached — log but DO NOT crash, try to download anyway
        print(f"[Step 4] ⚠️  Render timeout after {RENDER_TIMEOUT // 60} min — attempting download anyway...")

    # ✅ FIX: Extra settle time before download attempts
    time.sleep(5)

    # Dismiss the "generated" popup (click × or close)
    for sel in [
        ".arco-modal-close-btn",
        "button:has-text('×')",
        "[aria-label='Close']",
        ".popup-close",
    ]:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
        except Exception:
            pass
    time.sleep(2)

    # ── Extract metadata ──────────────────────────────────────────────────────
    video_id = page.url.strip("/").split("/")[-1]
    if not video_id or len(video_id) < 3:
        video_id = f"gen_{int(time.time())}"

    gen_title = ""
    try:
        for sel in ["h1", ".project-title", "input.title-input"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = (el.first.text_content() or el.first.get_attribute("value") or "").strip()
                if t:
                    gen_title = t
                    break
    except Exception:
        pass

    hashtags = ""
    try:
        tags = page.locator("[class*='hashtag'], [class*='tag-item']").all()
        hashtags = " ".join(t.text_content().strip() for t in tags if t.text_content())
    except Exception:
        pass

    # ── Download thumbnail ────────────────────────────────────────────────────
    thumb_local = ""
    thumb_web = ""
    try:
        thumb_img = page.locator(
            "[class*='thumbnail'] img, "
            "[class*='cover-img'] img, "
            "[class*='magic-thumbnail'] img"
        )
        if thumb_img.count() > 0:
            thumb_web = thumb_img.first.get_attribute("src") or ""
            if thumb_web:
                resp = requests.get(thumb_web, timeout=30)
                ext = ".jpg"
                dest = os.path.join(DOWNLOADS_DIR, f"{row_label}_thumb{ext}")
                with open(dest, "wb") as f:
                    f.write(resp.content)
                thumb_local = dest
                print(f"[Download] ✓ Thumbnail saved: {dest}")
    except Exception as e:
        print(f"[Download] Thumbnail failed: {e}")

    # ── Download video ────────────────────────────────────────────────────────
    # ✅ FIX: Increased download button wait from 120s → 180s
    video_local = ""
    try:
        print("[Download] Clicking Download Video button...")
        dl_btn = page.locator("button:has-text('Download'), a:has-text('Download')")
        if dl_btn.count() > 0:
            with page.expect_download(timeout=180000) as dl_info:
                dl_btn.first.click()
            dl: Download = dl_info.value
            dest = os.path.join(DOWNLOADS_DIR, f"{row_label}_{dl.suggested_filename or 'video.mp4'}")
            dl.save_as(dest)
            video_local = dest
            print(f"[Download] ✓ Video saved: {dest}")
        else:
            print("[Download] No download button visible.")
    except Exception as e:
        print(f"[Download] Video download failed: {e}")

    return {
        "video_id":    video_id,
        "gen_title":   gen_title,
        "hashtags":    hashtags,
        "thumb_local": thumb_local,
        "thumb_web":   thumb_web,
        "video_local": video_local,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    limit = args.maxstory if args.maxstory is not None else STORIES_PER_RUN

    print("=" * 60)
    print(f"  AutoMagicAI — MagicLight.AI Automation")
    print(f"  Stories this run: {limit} | Headless: {args.headless}")
    print("=" * 60)

    if not SPREADSHEET_ID:
        print("[ERROR] SPREADSHEET_ID not set in .env"); return
    if not ML_EMAIL or not ML_PASSWORD:
        print("[ERROR] ML_EMAIL / ML_PASSWORD not set in .env"); return

    # Google Sheets
    print("[Setup] Connecting to Google Sheets...")
    sheet = get_sheet()
    if not sheet:
        return
    records = sheet.get_all_records()
    print(f"[Setup] Found {len(records)} rows in sheet.")

    # Google Drive
    drive_service = None
    if DRIVE_FOLDER_ID:
        try:
            drive_service = get_drive_service()
            print("[Setup] ✓ Google Drive connected.")
        except Exception as e:
            print(f"[Setup] Drive error (upload disabled): {e}")
    else:
        print("[Setup] GOOGLE_DRIVE_FOLDER_ID not set — Drive upload disabled.")

    # Launch browser
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless,
            args=["--start-maximized"],
        )
        browser_instance = browser  # Store for graceful shutdown
        context = browser.new_context(
            accept_downloads=True,
            no_viewport=True,
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
            # Check for graceful shutdown request
            if shutdown_requested:
                print(f"\n[SHUTDOWN] Graceful shutdown requested. Stopping after {processed} stories.")
                break
                
            if processed >= limit:
                print(f"\n[Limit] Reached {limit} stories. Stopping.")
                break

            if row.get("Status", "").strip().lower() == "generated":
                continue

            story = row.get("Story Text", "").strip()
            if not story:
                continue

            title_hint = row.get("Title", f"Row_{idx}").strip() or f"Row_{idx}"
            moral = row.get("Moral", "").strip()
            row_label = f"row{idx}_{title_hint[:30].replace(' ', '_')}"

            prompt = story
            if moral:
                prompt += f"\n\nMoral of the story: {moral}"

            print(f"\n{'='*60}")
            print(f"[Processing] Row {idx}: {title_hint}")
            print(f"{'='*60}")

            # Check for shutdown before starting story processing
            if shutdown_requested:
                print(f"[SHUTDOWN] Graceful shutdown requested before processing row {idx}.")
                break

            try:
                # Run the full generation pipeline
                step1_content(page, prompt)
                step2_cast(page)
                step3_storyboard(page)
                result = step4_generate_and_download(page, row_label)

                final_title = result["gen_title"] or title_hint

                # Drive upload
                drive_video_url = ""
                drive_thumb_url = ""
                if drive_service and DRIVE_FOLDER_ID:
                    try:
                        folder_name = f"Row_{idx}_{final_title[:40]}"
                        sub_id = create_drive_folder(drive_service, folder_name, DRIVE_FOLDER_ID)
                        if result["video_local"] and os.path.exists(result["video_local"]):
                            drive_video_url = upload_to_drive(drive_service, result["video_local"], sub_id)
                            print(f"[Drive] ✓ Video → {drive_video_url}")
                        if result["thumb_local"] and os.path.exists(result["thumb_local"]):
                            drive_thumb_url = upload_to_drive(drive_service, result["thumb_local"], sub_id)
                            print(f"[Drive] ✓ Thumbnail → {drive_thumb_url}")
                    except Exception as e:
                        print(f"[Drive] Upload error: {e}")

                # Update sheet
                notes = f"Title: {final_title}"
                if result["hashtags"]:
                    notes += f" | Tags: {result['hashtags']}"

                sheet.update_cell(idx, COL_STATUS,    "Generated")
                sheet.update_cell(idx, COL_VIDEO_ID,  result["video_id"])
                sheet.update_cell(idx, COL_THUMB_URL, drive_thumb_url or result["thumb_web"])
                sheet.update_cell(idx, COL_VIDEO_URL, drive_video_url)
                sheet.update_cell(idx, COL_NOTES,     notes)
                print(f"[Sheet] ✓ Row {idx} updated.")
                processed += 1

            except Exception as e:
                print(f"[ERROR] Row {idx} failed: {e}")
                try:
                    sheet.update_cell(idx, COL_STATUS, "Error")
                    sheet.update_cell(idx, COL_NOTES,  str(e)[:500])
                except Exception:
                    pass

        print(f"\n{'='*60}")
        print(f"  Done! Processed {processed}/{limit} stories.")
        print(f"{'='*60}")
        
        if not shutdown_requested:
            input("Press Enter to close the browser...")
        
        browser.close()
        browser_instance = None  # Clear the reference


if __name__ == "__main__":
    main()
