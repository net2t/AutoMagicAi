"""
AutoMagicAI — Automated video generation from Google Sheets using MagicLight.AI
Author: net2t (net2tara@gmail.com)
Repo:   https://github.com/net2t/AutoMagicAi
"""

import os
import sys
import json
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

# ── Load config ───────────────────────────────────────────────────────────────
load_dotenv()

SPREADSHEET_ID  = os.getenv("SPREADSHEET_ID", "")
ML_EMAIL        = os.getenv("ML_EMAIL", "")
ML_PASSWORD     = os.getenv("ML_PASSWORD", "")
STORIES_PER_RUN = int(os.getenv("STORIES_PER_RUN", "2"))
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

# ── Per-step timing controls (all configurable via .env) ──────────────────────
STEP1_WAIT           = int(os.getenv("STEP1_WAIT",           "60"))   # seconds to wait after Step 1 Next click
STEP2_WAIT           = int(os.getenv("STEP2_WAIT",           "20"))   # seconds to wait for Cast to generate
STEP3_WAIT           = int(os.getenv("STEP3_WAIT",           "180"))  # seconds to wait for Storyboard images
STEP4_RENDER_TIMEOUT = int(os.getenv("STEP4_RENDER_TIMEOUT", "900"))  # seconds to wait for video render (15 min)
STEP4_POLL_INTERVAL  = int(os.getenv("STEP4_POLL_INTERVAL",  "15"))   # how often to check render status
STEP4_MAX_NEXT       = int(os.getenv("STEP4_MAX_NEXT",       "10"))   # max Next clicks before reaching Generate

CREDS_FILE    = "credentials.json"
COOKIES_FILE  = "cookies.json"
DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# ── Google API scopes ─────────────────────────────────────────────────────────
SHEETS_SCOPES = ["https://spreadsheets.google.com/feeds",
                 "https://www.googleapis.com/auth/drive"]
DRIVE_SCOPES  = ["https://www.googleapis.com/auth/drive"]

# ── Sheet column indices (1-based) ────────────────────────────────────────────
# A=Theme  B=Title  C=Story  D=Moral  E=Hashtags  F=Date  G=Status
# H=MagicThumbnail  I=VideoID  J=Title(gen)  K=Summary  L=Hashtags(gen)
# M=Notes  N=ProjectURL
COL_THEME       = 1
COL_TITLE       = 2
COL_STORY       = 3
COL_MORAL       = 4
COL_HASHTAGS    = 5
COL_DATE        = 6
COL_STATUS      = 7
COL_THUMB_URL   = 8   # H — Magic Thumbnail URL
COL_VIDEO_ID    = 9   # I — VideoID
COL_GEN_TITLE   = 10  # J — Generated Title
COL_SUMMARY     = 11  # K — Summary
COL_GEN_HASH    = 12  # L — Generated Hashtags
COL_NOTES       = 13  # M — Notes
COL_PROJECT_URL = 14  # N — Project URL (NEW)

# ── Graceful shutdown ─────────────────────────────────────────────────────────
shutdown_requested = False
browser_instance   = None

def signal_handler(signum, frame):
    global shutdown_requested, browser_instance
    print("\n[SHUTDOWN] CTRL+C detected — finishing current step then stopping...")
    shutdown_requested = True
    if browser_instance:
        try:
            browser_instance.close()
        except Exception:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(description="AutoMagicAI — Kids Story video generator")
    p.add_argument("--maxstory", "-n", type=int, default=None,
                   help="Stories to process (overrides .env STORIES_PER_RUN)")
    p.add_argument("--headless", action="store_true", default=False,
                   help="Run browser headless (no window)")
    return p.parse_args()


# ── Google Sheets ─────────────────────────────────────────────────────────────
def get_sheet():
    try:
        creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SHEETS_SCOPES)
        client = gspread.authorize(creds)
        return client.open_by_key(SPREADSHEET_ID).sheet1
    except Exception as e:
        print(f"[ERROR] Google Sheets: {e}")
        return None


# ── Google Drive ──────────────────────────────────────────────────────────────
def get_drive_service():
    creds = GACredentials.from_service_account_file(CREDS_FILE, scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)

def create_drive_folder(service, name: str, parent_id: str) -> str:
    meta   = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]

def upload_to_drive(service, local_path: str, folder_id: str) -> str:
    name   = os.path.basename(local_path)
    mime   = "video/mp4" if local_path.endswith(".mp4") else "image/jpeg"
    media  = MediaFileUpload(local_path, mimetype=mime, resumable=True)
    f_meta = {"name": name, "parents": [folder_id]}
    upl    = service.files().create(body=f_meta, media_body=media, fields="id,webViewLink").execute()
    service.permissions().create(fileId=upl["id"], body={"role": "reader", "type": "anyone"}).execute()
    return upl.get("webViewLink", "")


# ── Cookie helpers ────────────────────────────────────────────────────────────
def save_cookies(context):
    """Save browser cookies to cookies.json for reuse."""
    try:
        cookies = context.cookies()
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"[Cookies] ✓ Saved {len(cookies)} cookies to {COOKIES_FILE}")
    except Exception as e:
        print(f"[Cookies] Could not save: {e}")

def load_cookies(context) -> bool:
    """Load cookies from cookies.json into the browser context. Returns True if loaded."""
    if not os.path.exists(COOKIES_FILE):
        return False
    try:
        with open(COOKIES_FILE) as f:
            cookies = json.load(f)
        if not cookies:
            return False
        context.add_cookies(cookies)
        print(f"[Cookies] ✓ Loaded {len(cookies)} saved cookies")
        return True
    except Exception as e:
        print(f"[Cookies] Could not load: {e}")
        return False

def clear_cookies():
    """Delete saved cookies (used when login fails with saved cookies)."""
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)
        print("[Cookies] Cleared stale cookies.json")


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


# ── Popup / tour helpers ──────────────────────────────────────────────────────
def dismiss_popups(page):
    for sel in [".arco-modal-close-btn", "button:has-text('OK')", "button:has-text('Got it')",
                "button:has-text('Close')", "[aria-label='Close']",
                ".sora2-modal .close", ".notice-popup-modal__close"]:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(0.5)
        except Exception:
            pass

def _dismiss_tour(page):
    try:
        time.sleep(3)
        print("[Tour] Checking for tutorial overlays...")
        js_click = """() => {
            const texts = ["Skip","Got it","Got It","Close","Done"];
            document.querySelectorAll('button,span,div,a').forEach(el => {
                if (el.innerText && texts.includes(el.innerText.trim())) el.click();
            });
        }"""
        for _ in range(3):
            page.evaluate(js_click)
            time.sleep(1)
        page.evaluate("""() => {
            document.querySelectorAll('.diy-tour,.diy-tour__mask,[class*="tour-tooltip"],[class*="driver-"]')
                .forEach(el => { try { el.remove(); } catch(e){} });
        }""")
        time.sleep(1)
    except Exception as e:
        print(f"[Tour] {e}")

def _dismiss_animation_modal(page):
    """
    Dismiss the 'Animate All' modal that blocks the Generate button.
    Tries multiple strategies to ensure it's fully closed.
    """
    # Strategy 1: click arco-btn-secondary with text Next/Skip
    js1 = """() => {
        const btns = Array.from(document.querySelectorAll(
            'button.arco-btn-secondary, .arco-modal-footer button, .arco-modal button'
        ));
        for (const el of btns) {
            const t = (el.innerText || '').trim();
            const rect = el.getBoundingClientRect();
            if ((t === 'Next' || t === 'Skip' || t === 'Cancel' || t === 'No thanks')
                && rect.width > 0 && rect.height > 0) {
                el.click();
                return 'secondary: ' + t;
            }
        }
        return null;
    }"""
    # Strategy 2: close any arco-modal via X button
    js2 = """() => {
        const close = document.querySelector(
            '.arco-modal-close-btn, [aria-label="Close"], .modal-close, .animation-modal__close'
        );
        if (close) { close.click(); return 'modal X closed'; }
        return null;
    }"""
    # Strategy 3: force-remove the modal DOM element
    js3 = """() => {
        const modals = document.querySelectorAll(
            '.arco-modal-wrapper, .animation-modal, [class*="animation-modal"]'
        );
        let removed = 0;
        modals.forEach(el => { try { el.remove(); removed++; } catch(e){} });
        return removed > 0 ? 'removed ' + removed + ' modal(s)' : null;
    }"""
    for js in [js1, js2, js3]:
        try:
            result = page.evaluate(js)
            if result:
                print(f"[Modal] ✓ {result}")
                time.sleep(2)
                return
        except Exception:
            pass


# ── DOM helpers ───────────────────────────────────────────────────────────────
def _dom_click_text(page, texts: list, timeout: int = 120) -> bool:
    js = """(texts) => {
        const all = Array.from(document.querySelectorAll(
            'button,div[class*="btn"],span[class*="btn"],a,div[class*="vlog-btn"],div[class*="footer-btn"]'
        ));
        for (let i = all.length - 1; i >= 0; i--) {
            const el = all[i];
            let dt = '';
            el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) dt += n.textContent; });
            const t = dt.trim() || (el.innerText || '').trim();
            if (texts.includes(t)) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) { el.click(); return t; }
            }
        }
        return null;
    }"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = page.evaluate(js, texts)
        if result:
            print(f"[DOM] ✓ Clicked '{result}'")
            return True
        time.sleep(3)
    return False

def _dom_click_class(page, css_class: str, timeout: int = 30) -> bool:
    js = f"""() => {{
        const all = Array.from(document.querySelectorAll('[class*="{css_class}"]'));
        for (let i = all.length - 1; i >= 0; i--) {{
            const el = all[i];
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {{ el.click(); return el.className; }}
        }}
        return null;
    }}"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = page.evaluate(js)
        if result:
            print(f"[DOM] ✓ Clicked class ~'{css_class}'")
            return True
        time.sleep(3)
    return False

def _dom_debug_buttons(page):
    js = """() => {
        const all = Array.from(document.querySelectorAll(
            'button,div[class*="btn"],span[class*="btn"],a,div[class*="vlog-btn"]'
        ));
        const res = [];
        all.forEach(el => {
            const t = (el.innerText || '').trim().substring(0, 60);
            const r = el.getBoundingClientRect();
            if (t && r.width > 0 && r.height > 0)
                res.push(el.tagName + '.' + (el.className||'').substring(0,40) + ' | ' + t);
        });
        return res;
    }"""
    try:
        items = page.evaluate(js)
        print(f"[DEBUG] URL: {page.url}")
        print("[DEBUG] Visible buttons:")
        for item in (items or []):
            print(f"  {item}")
    except Exception as e:
        print(f"[DEBUG] {e}")

def _click_next_header(page):
    """Click the header-shiny-action__btn Next div and dismiss any animation modal."""
    js = """() => {
        const divs = Array.from(document.querySelectorAll('[class*="header-shiny-action__btn"]'));
        for (const el of divs) {
            const t = (el.innerText || '').trim();
            const r = el.getBoundingClientRect();
            if (t === 'Next' && r.width > 0 && r.height > 0) { el.click(); return 'header Next'; }
        }
        const btns = Array.from(document.querySelectorAll('button.arco-btn-primary, button'));
        for (const el of btns) {
            const t = (el.innerText || '').trim();
            const r = el.getBoundingClientRect();
            if (t === 'Next' && r.width > 0 && r.height > 0) { el.click(); return 'button Next'; }
        }
        return null;
    }"""
    result = page.evaluate(js)
    if result:
        print(f"[Step 4] ✓ {result}")
    return result


# ── Step 1: Content ───────────────────────────────────────────────────────────
def step1_content(page, story_text: str):
    print("[Step 1] Navigating to Kids Story page...")
    page.goto("https://magiclight.ai/kids-story/", timeout=60000)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(6)
    dismiss_popups(page)
    _dismiss_tour(page)

    print("[Step 1] Pasting story text...")
    textarea = page.locator("textarea[placeholder*='original story']")
    textarea.wait_for(state="visible", timeout=20000)
    textarea.first.evaluate(
        f"el => {{ el.value = {repr(story_text)}; "
        f"el.dispatchEvent(new Event('input', {{bubbles:true}})); }}"
    )
    time.sleep(1)

    print("[Step 1] Selecting Pixar 2.0 style...")
    try:
        pixar = page.locator("text='Pixar 2.0'")
        if pixar.count() > 0 and pixar.first.is_visible():
            pixar.first.click()
            time.sleep(1)
    except Exception:
        print("[Step 1] Pixar 2.0 not found — skipping")

    try:
        r169 = page.locator("text='16:9'")
        if r169.count() > 0 and r169.first.is_visible():
            r169.first.click()
    except Exception:
        pass

    print(f"[Step 1] Clicking Next (will wait {STEP1_WAIT}s after)...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)

    # Click Next using _dom_click_text for robustness
    deadline = time.time() + 20
    while time.time() < deadline:
        for sel in ["button.arco-btn-primary:has-text('Next')", "button:has-text('Next')"]:
            try:
                btn = page.locator(sel).last
                if btn.is_visible():
                    btn.click()
                    time.sleep(STEP1_WAIT)
                    return
            except Exception:
                pass
        time.sleep(2)
    raise Exception("[Step 1] Could not find Next button")


# ── Step 2: Cast ──────────────────────────────────────────────────────────────
def step2_cast(page):
    print(f"[Step 2] Cast — waiting {STEP2_WAIT}s for characters to generate...")
    time.sleep(STEP2_WAIT)
    dismiss_popups(page)

    print("[Step 2] Clicking Next Step...")
    if _dom_click_class(page, "step2-footer-btn-left", timeout=120):
        print("[Step 2] ✓ Done.")
    elif _dom_click_text(page, ["Next Step", "Animate All", "Create now"], timeout=30):
        print("[Step 2] ✓ Done (fallback).")
    else:
        _dom_debug_buttons(page)
        print("[Step 2] Next Step not found — may have auto-skipped.")

    time.sleep(4)
    _dismiss_animation_modal(page)
    time.sleep(4)


# ── Step 3: Storyboard ────────────────────────────────────────────────────────
def step3_storyboard(page):
    print(f"[Step 3] Storyboard — waiting up to {STEP3_WAIT}s for images...")
    dismiss_popups(page)

    js_count = """() => {
        const imgs = document.querySelectorAll(
            '[class*="role-card"] img,[class*="scene"] img,[class*="storyboard"] img,'
            '[class*="story-board"] img,[class*="video-scene"] img,[class*="frame"] img'
        );
        return imgs.length;
    }"""
    deadline = time.time() + STEP3_WAIT
    while time.time() < deadline:
        count = page.evaluate(js_count)
        if count >= 2:
            print(f"[Step 3] ✓ Storyboard images ready ({count} found)")
            break
        time.sleep(5)
        print(f"[Step 3] Waiting for images... ({int(deadline - time.time())}s left)")
    else:
        print("[Step 3] Timeout — proceeding anyway")

    time.sleep(3)

    print("[Step 3] Clicking Next Step...")
    if _dom_click_class(page, "step2-footer-btn-left", timeout=20):
        print("[Step 3] ✓ Done.")
    elif _dom_click_text(page, ["Next", "Next Step", "Create now"], timeout=15):
        print("[Step 3] ✓ Done (fallback).")
    else:
        _dom_debug_buttons(page)
        print("[Step 3] Next not found — proceeding to Step 4.")

    time.sleep(4)
    _dismiss_animation_modal(page)
    time.sleep(4)


# ── Step 4: Edit → Generate → Wait → Download ─────────────────────────────────
def step4_generate_and_download(page, row_label: str, safe_title: str) -> dict:
    print("[Step 4] Navigating sub-steps to reach Generate screen...")
    dismiss_popups(page)
    time.sleep(3)

    generate_texts = ["Generate", "Create Video", "Export", "Create now", "Render"]

    # ── Navigate to Generate button ──────────────────────────────────────────
    # KEY FIX: Dismiss animation modal FIRST on every attempt before checking
    for attempt in range(STEP4_MAX_NEXT):

        # Always dismiss animation modal at top of each attempt
        _dismiss_animation_modal(page)
        time.sleep(2)
        dismiss_popups(page)

        # Check if Generate is visible now
        js_has_generate = """(texts) => {
            const all = Array.from(document.querySelectorAll(
                'button,div[class*="btn"],span[class*="btn"],div[class*="footer-btn"]'
            ));
            for (let i = all.length - 1; i >= 0; i--) {
                const el = all[i];
                let dt = '';
                el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) dt += n.textContent; });
                const t = dt.trim() || (el.innerText || '').trim();
                if (texts.includes(t)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) return t;
                }
            }
            return null;
        }"""
        found = page.evaluate(js_has_generate, generate_texts)
        if found:
            print(f"[Step 4] ✓ Found '{found}' button after {attempt} Next clicks!")
            break

        print(f"[Step 4] Generate not visible (attempt {attempt+1}/{STEP4_MAX_NEXT}) — clicking Next...")
        result = _click_next_header(page)
        if not result:
            print("[Step 4] No Next button found at all")
            _dom_debug_buttons(page)

        time.sleep(4)   # Wait a bit longer after each Next click
        _dismiss_animation_modal(page)
        time.sleep(3)
        dismiss_popups(page)

    else:
        _dom_debug_buttons(page)
        raise Exception(f"[Step 4] Could not reach Generate after {STEP4_MAX_NEXT} attempts")

    # ── Click Generate ────────────────────────────────────────────────────────
    print("[Step 4] Clicking Generate...")
    if not _dom_click_text(page, generate_texts, timeout=20):
        _dom_debug_buttons(page)
        raise Exception("[Step 4] Generate button click failed")
    time.sleep(3)

    # ── Confirm export popup ──────────────────────────────────────────────────
    print("[Step 4] Confirming export popup (OK)...")
    _dom_click_text(page, ["OK", "Ok", "Confirm"], timeout=10)
    time.sleep(3)
    dismiss_popups(page)

    # ── Wait for render ───────────────────────────────────────────────────────
    PROGRESS_EVERY = 30
    print(f"[Step 4] ⏳ Waiting for render (up to {STEP4_RENDER_TIMEOUT // 60} min)...")
    print("[Step 4]    MagicLight usually takes 5–10 minutes — please be patient...")

    start              = time.time()
    last_progress_log  = start
    render_done        = False

    while time.time() - start < STEP4_RENDER_TIMEOUT:
        elapsed = int(time.time() - start)

        # Check 1: success popup text
        for txt in ["video has been generated", "Video generated", "generation complete",
                    "successfully generated", "video is ready", "Your video is ready"]:
            try:
                if page.locator(f"text='{txt}'").count() > 0:
                    print(f"[Step 4] ✓ Render complete: '{txt}' ({elapsed}s)")
                    render_done = True
                    break
            except Exception:
                pass
        if render_done:
            break

        # Check 2: Download video button appeared
        try:
            dl = page.locator(
                "button:has-text('Download video'), a:has-text('Download video'),"
                "[class*='download-btn'], [class*='download_btn']"
            )
            if dl.count() > 0 and dl.first.is_visible():
                print(f"[Step 4] ✓ Download button visible ({elapsed}s)")
                render_done = True
                break
        except Exception:
            pass

        # Check 3: "Download video" text anywhere on page
        try:
            if page.locator("text='Download video'").count() > 0:
                print(f"[Step 4] ✓ 'Download video' text detected ({elapsed}s)")
                render_done = True
                break
        except Exception:
            pass

        # Progress log
        if time.time() - last_progress_log >= PROGRESS_EVERY:
            mins = elapsed // 60
            secs = elapsed % 60
            rem  = STEP4_RENDER_TIMEOUT - elapsed
            print(f"[Step 4] ⏳ {mins}m {secs}s elapsed | "
                  f"{rem // 60}m {rem % 60}s remaining...")
            last_progress_log = time.time()

        time.sleep(STEP4_POLL_INTERVAL)

    if not render_done:
        print(f"[Step 4] ⚠️  Render timeout ({STEP4_RENDER_TIMEOUT // 60} min) — trying to download anyway...")

    time.sleep(5)  # Settle buffer

    # ── Dismiss success popup ─────────────────────────────────────────────────
    for sel in [".arco-modal-close-btn", "button:has-text('×')",
                "[aria-label='Close']", ".popup-close"]:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
        except Exception:
            pass
    time.sleep(2)

    # ── Extract metadata from the final result page ───────────────────────────
    video_id = page.url.strip("/").split("/")[-1]
    if not video_id or len(video_id) < 3:
        video_id = f"gen_{int(time.time())}"

    # Generated Title (from h1 or input)
    gen_title = ""
    try:
        for sel in ["h1", ".project-title", "input.title-input", "[class*='project-name']"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = (el.first.text_content() or el.first.get_attribute("value") or "").strip()
                if t:
                    gen_title = t
                    break
    except Exception:
        pass

    # Summary (from the Summary panel)
    summary = ""
    try:
        for sel in ["[class*='summary'] p", "[class*='summary'] div",
                    "textarea[class*='summary']", ".video-summary", "[class*='video-desc']"]:
            el = page.locator(sel)
            if el.count() > 0:
                t = (el.first.text_content() or "").strip()
                if t and len(t) > 10:
                    summary = t
                    break
    except Exception:
        pass

    # Hashtags (from hashtag chips)
    hashtags = ""
    try:
        tags = page.locator("[class*='hashtag'], [class*='tag-item'], [class*='hash-tag']").all()
        hashtags = " ".join(t.text_content().strip() for t in tags if t.text_content())
    except Exception:
        pass

    # ── Build local folder ────────────────────────────────────────────────────
    # Folder name: Row_2_Luna_and_the_Lantern  (safe for filesystem)
    local_folder = os.path.join(DOWNLOADS_DIR, safe_title)
    os.makedirs(local_folder, exist_ok=True)
    print(f"[Download] Local folder: {local_folder}")

    # ── Download Magic Thumbnail ──────────────────────────────────────────────
    thumb_local = ""
    thumb_web   = ""
    try:
        # The Magic Thumbnail is inside a specific container
        thumb_img = page.locator(
            "[class*='magic-thumbnail'] img, "
            "[class*='thumbnail'] img, "
            "[class*='cover-img'] img"
        )
        if thumb_img.count() > 0:
            thumb_web = thumb_img.first.get_attribute("src") or ""
            if thumb_web:
                resp = requests.get(thumb_web, timeout=30)
                dest = os.path.join(local_folder, f"{safe_title}_thumbnail.jpg")
                with open(dest, "wb") as f:
                    f.write(resp.content)
                thumb_local = dest
                print(f"[Download] ✓ Thumbnail → {dest}")
    except Exception as e:
        print(f"[Download] Thumbnail failed: {e}")

    # ── Download Video ────────────────────────────────────────────────────────
    video_local = ""
    try:
        print("[Download] Waiting for Download Video button...")
        # Look for the specific "Download video" button (not Download thumbnail)
        dl_btn = page.locator(
            "button:has-text('Download video'), "
            "a:has-text('Download video'), "
            "button:has-text('Download'), "
            "a:has-text('Download')"
        )
        # Wait up to 30s for download button
        deadline = time.time() + 30
        while time.time() < deadline:
            if dl_btn.count() > 0 and dl_btn.first.is_visible():
                break
            time.sleep(3)

        if dl_btn.count() > 0:
            with page.expect_download(timeout=180000) as dl_info:
                dl_btn.first.click()
            dl: Download = dl_info.value
            dest = os.path.join(local_folder, f"{safe_title}.mp4")
            dl.save_as(dest)
            video_local = dest
            print(f"[Download] ✓ Video → {dest}")
        else:
            print("[Download] No download button found.")
    except Exception as e:
        print(f"[Download] Video failed: {e}")

    return {
        "video_id":    video_id,
        "gen_title":   gen_title,
        "summary":     summary,
        "hashtags":    hashtags,
        "thumb_local": thumb_local,
        "thumb_web":   thumb_web,
        "video_local": video_local,
        "local_folder": local_folder,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    global browser_instance

    args  = parse_args()
    limit = args.maxstory if args.maxstory is not None else STORIES_PER_RUN

    print("=" * 60)
    print(f"  AutoMagicAI — MagicLight.AI Automation")
    print(f"  Stories this run : {limit} | Headless: {args.headless}")
    print(f"  Timing  → Step1:{STEP1_WAIT}s  Step2:{STEP2_WAIT}s  "
          f"Step3:{STEP3_WAIT}s  Render:{STEP4_RENDER_TIMEOUT}s")
    print("=" * 60)

    if not SPREADSHEET_ID:
        print("[ERROR] SPREADSHEET_ID not set in .env"); return
    if not ML_EMAIL or not ML_PASSWORD:
        print("[ERROR] ML_EMAIL / ML_PASSWORD not set in .env"); return

    print("[Setup] Connecting to Google Sheets...")
    sheet = get_sheet()
    if not sheet:
        return
    # Get all data and handle duplicate headers manually
    all_data = sheet.get_all_values()
    if len(all_data) < 2:
        print("[ERROR] Sheet is empty or has no data rows")
        return
    
    headers = all_data[0]  # First row is headers
    records = []
    
    for row in all_data[1:]:  # Skip header row
        if len(row) >= len(headers):
            record = {}
            for i, header in enumerate(headers):
                if i < len(row):
                    record[header] = row[i]
                else:
                    record[header] = ""
            records.append(record)
    print(f"[Setup] Found {len(records)} rows in sheet.")

    drive_service = None
    if DRIVE_FOLDER_ID:
        try:
            drive_service = get_drive_service()
            print("[Setup] ✓ Google Drive connected.")
        except Exception as e:
            print(f"[Setup] Drive error (upload disabled): {e}")
    else:
        print("[Setup] GOOGLE_DRIVE_FOLDER_ID not set — Drive upload disabled.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, args=["--start-maximized"])
        browser_instance = browser
        context = browser.new_context(accept_downloads=True, no_viewport=True)
        page    = context.new_page()

        try:
            login(page)
        except Exception as e:
            print(f"[FATAL] Login failed: {e}")
            browser.close()
            return

        processed = 0

        for idx, row in enumerate(records, start=2):
            if shutdown_requested:
                print(f"\n[SHUTDOWN] Stopping after {processed} stories.")
                break
            if processed >= limit:
                print(f"\n[Limit] Reached {limit} stories. Stopping.")
                break

            status = row.get("Status", "").strip().lower()

            # ── Only process stories with "Generated" status ────────────────────────────
            if status != "generated":
                continue

            # ── Check for pending retry (has a Project URL saved) ─────────────
            project_url = str(row.get("Project URL", "") or "").strip()
            story       = row.get("Story", "").strip()
            if not story:
                continue

            title_hint = (row.get("Title", "") or f"Row_{idx}").strip() or f"Row_{idx}"
            moral      = row.get("Moral", "").strip()

            # Build a filesystem-safe folder name
            safe_title = f"Row_{idx}_{title_hint[:40]}".replace(" ", "_") \
                           .replace("/", "_").replace("\\", "_") \
                           .replace(":", "_").replace("*", "_") \
                           .replace("?", "_").replace('"', "_") \
                           .replace("<", "_").replace(">", "_") \
                           .replace("|", "_")

            prompt = story
            if moral:
                prompt += f"\n\nMoral of the story: {moral}"

            print(f"\n{'='*60}")
            print(f"[Processing] Row {idx}: {title_hint}")
            if project_url:
                print(f"[Processing] Retry mode — using saved Project URL: {project_url}")
            print(f"{'='*60}")

            try:
                # ── If we have a saved project URL, jump straight to Step 4 ──
                if project_url and "magiclight.ai/project/edit/" in project_url:
                    print(f"[Retry] Navigating to saved project: {project_url}")
                    page.goto(project_url, timeout=60000)
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(6)
                    dismiss_popups(page)
                    _dismiss_tour(page)
                    result = step4_generate_and_download(page, safe_title, safe_title)

                else:
                    # ── Full pipeline ─────────────────────────────────────────
                    step1_content(page, prompt)

                    # ── Save Project URL immediately after Step 1 ─────────────
                    # The URL changes to /project/edit/<id> after clicking Next on Step 1
                    time.sleep(3)
                    current_url = page.url
                    if "project/edit" in current_url:
                        try:
                            sheet.update_cell(idx, COL_PROJECT_URL, current_url)
                            sheet.update_cell(idx, COL_STATUS, "Pending")
                            print(f"[Sheet] ✓ Project URL saved: {current_url}")
                        except Exception as e:
                            print(f"[Sheet] Could not save Project URL: {e}")

                    step2_cast(page)
                    step3_storyboard(page)
                    result = step4_generate_and_download(page, safe_title, safe_title)

                # ── Drive Upload ──────────────────────────────────────────────
                drive_video_url = ""
                drive_thumb_url = ""
                if drive_service and DRIVE_FOLDER_ID:
                    try:
                        # Create Drive folder with same name as local folder
                        drive_subfolder_id = create_drive_folder(
                            drive_service, safe_title, DRIVE_FOLDER_ID
                        )
                        print(f"[Drive] ✓ Folder created: {safe_title}")

                        if result["video_local"] and os.path.exists(result["video_local"]):
                            drive_video_url = upload_to_drive(
                                drive_service, result["video_local"], drive_subfolder_id
                            )
                            print(f"[Drive] ✓ Video → {drive_video_url}")

                        if result["thumb_local"] and os.path.exists(result["thumb_local"]):
                            drive_thumb_url = upload_to_drive(
                                drive_service, result["thumb_local"], drive_subfolder_id
                            )
                            print(f"[Drive] ✓ Thumbnail → {drive_thumb_url}")

                    except Exception as e:
                        print(f"[Drive] Upload error: {e}")

                # ── Update Sheet with all results ─────────────────────────────
                final_title = result["gen_title"] or title_hint
                notes       = f"Generated OK | local: {result['local_folder']}"

                sheet.update_cell(idx, COL_STATUS,      "Generated")
                sheet.update_cell(idx, COL_THUMB_URL,   drive_thumb_url or result["thumb_web"])
                sheet.update_cell(idx, COL_VIDEO_ID,    result["video_id"])
                sheet.update_cell(idx, COL_GEN_TITLE,   final_title)
                sheet.update_cell(idx, COL_SUMMARY,     result["summary"])
                sheet.update_cell(idx, COL_GEN_HASH,    result["hashtags"])
                sheet.update_cell(idx, COL_NOTES,       notes)
                sheet.update_cell(idx, COL_PROJECT_URL, page.url)
                print(f"[Sheet] ✓ Row {idx} fully updated.")
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
        browser_instance = None


if __name__ == "__main__":
    main()
