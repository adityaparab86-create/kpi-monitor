"""
Take screenshots of all KPI Monitor dashboard pages.
Run: python3 docs/take_screenshots.py
Requires: playwright  (pip install playwright && playwright install chromium)
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"
OUT_DIR  = Path(__file__).parent / "screenshots"
OUT_DIR.mkdir(exist_ok=True)

VIEWPORT = {"width": 1400, "height": 860}


def wait_for_ready(page, timeout=15000):
    """Wait until the Streamlit spinner disappears."""
    try:
        page.wait_for_selector('img[alt="Running..."]', timeout=3000)
        page.wait_for_selector('img[alt="Running..."]', state="hidden", timeout=timeout)
    except Exception:
        pass
    time.sleep(0.8)


def nav_to(page, label: str):
    page.locator(f'[role="radiogroup"] label', has_text=label).first.click()
    wait_for_ready(page)


def scroll_to(page, px: int):
    page.eval_on_selector("section.stMain", f"el => el.scrollTop = {px}")
    time.sleep(0.4)


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(viewport=VIEWPORT)
        page    = ctx.new_page()

        print("Loading app…")
        page.goto(BASE_URL, wait_until="networkidle")
        wait_for_ready(page)

        # ── 1. KPI Scorecard (top) ────────────────────────────────────────────
        nav_to(page, "KPI Scorecard")
        scroll_to(page, 0)
        page.screenshot(path=str(OUT_DIR / "01_scorecard_top.png"), full_page=False)
        print("  01_scorecard_top.png")

        scroll_to(page, 600)
        page.screenshot(path=str(OUT_DIR / "02_scorecard_cards.png"), full_page=False)
        print("  02_scorecard_cards.png")

        # ── 2. Anomaly Alerts ────────────────────────────────────────────────
        nav_to(page, "Anomaly Alerts")
        scroll_to(page, 0)
        page.screenshot(path=str(OUT_DIR / "03_anomaly_alerts.png"), full_page=False)
        print("  03_anomaly_alerts.png")

        # ── 3. Entity Health — Region Heat Map ───────────────────────────────
        nav_to(page, "Entity Health")
        scroll_to(page, 0)
        # Ensure Region + Heat Map is selected
        page.locator('[role="radiogroup"] label', has_text="Region").first.click()
        wait_for_ready(page)
        page.locator('[role="radiogroup"] label', has_text="Heat Map").first.click()
        wait_for_ready(page)
        page.screenshot(path=str(OUT_DIR / "04_entity_heatmap_region.png"), full_page=False)
        print("  04_entity_heatmap_region.png")

        # ── 4. Entity Health — Branch Heat Map ──────────────────────────────
        page.locator('[role="radiogroup"] label', has_text="Branch").first.click()
        wait_for_ready(page)
        page.screenshot(path=str(OUT_DIR / "05_entity_heatmap_branch.png"), full_page=False)
        print("  05_entity_heatmap_branch.png")

        # ── 5. Entity Health — RM Leaderboard ───────────────────────────────
        page.locator('[role="radiogroup"] label', has_text="RM").first.click()
        wait_for_ready(page)
        page.screenshot(path=str(OUT_DIR / "06_entity_leaderboard_rm.png"), full_page=False)
        print("  06_entity_leaderboard_rm.png")

        # ── 6. Entity Health — Deep Dive ─────────────────────────────────────
        scroll_to(page, 99999)
        time.sleep(0.5)
        page.screenshot(path=str(OUT_DIR / "07_entity_deep_dive.png"), full_page=False)
        print("  07_entity_deep_dive.png")

        # ── 7. Region Leaderboard (back to Region + Leaderboard) ─────────────
        scroll_to(page, 0)
        page.locator('[role="radiogroup"] label', has_text="Region").first.click()
        wait_for_ready(page)
        page.locator('[role="radiogroup"] label', has_text="Leaderboard").first.click()
        wait_for_ready(page)
        page.screenshot(path=str(OUT_DIR / "08_entity_leaderboard_region.png"), full_page=False)
        print("  08_entity_leaderboard_region.png")

        # ── 8. Investigate Anomaly ───────────────────────────────────────────
        nav_to(page, "Investigate Anomaly")
        scroll_to(page, 0)
        page.screenshot(path=str(OUT_DIR / "09_investigate_anomaly.png"), full_page=False)
        print("  09_investigate_anomaly.png")

        browser.close()
        print(f"\nAll screenshots saved to: {OUT_DIR}")


if __name__ == "__main__":
    run()
