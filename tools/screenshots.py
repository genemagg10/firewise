"""Screenshots + checks of the site with headless Chromium (Playwright).
  FIREWISE_PASSWORD=... python3 tools/screenshots.py [BASE_URL] [OUT_PREFIX]
BASE_URL defaults to http://127.0.0.1:8765/ (python3 -m http.server 8765 --bind 127.0.0.1)."""
import asyncio, os, sys
from playwright.async_api import async_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
PFX = sys.argv[2] if len(sys.argv) > 2 else ""
PW = os.environ["FIREWISE_PASSWORD"]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
os.makedirs(OUT, exist_ok=True)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        errors, results = [], {}
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
        shot = lambda name, **k: pg.screenshot(path=f"{OUT}/{PFX}{name}", **k)
        await pg.goto(BASE + "index.html", wait_until="networkidle"); await pg.wait_for_timeout(500)
        await shot("01-overview-locked.png")
        await pg.goto(BASE + "events.html", wait_until="networkidle"); await pg.wait_for_timeout(500)
        await shot("02-events-public.png", full_page=True)
        await pg.goto(BASE + "map.html", wait_until="networkidle"); await pg.wait_for_selector(".lock-overlay")
        await shot("03-lock-screen.png")
        await pg.fill("#lock-pw", "wrong-password-123"); await pg.click(".lock-card button[type=submit]")
        await pg.wait_for_function("document.querySelector('.lock-error').textContent.length > 0", timeout=20000)
        results["wrong_password_error"] = await pg.inner_text(".lock-error")
        results["markers_while_locked"] = await pg.evaluate("document.querySelectorAll('path.leaflet-interactive').length")
        await shot("04-wrong-password.png")
        await pg.fill("#lock-pw", PW); await pg.click(".lock-card button[type=submit]")
        await pg.wait_for_selector(".lock-overlay", state="detached", timeout=20000); await pg.wait_for_timeout(1500)
        results["markers_unlocked"] = await pg.evaluate("document.querySelectorAll('path.leaflet-interactive').length")
        results["summary"] = (await pg.inner_text("#summary")).replace("\n", " / ")
        await shot("05-map-unlocked.png")
        m = await pg.evaluate("() => { const m = window._fwMarkers[0]; m.openPopup(); return m._r.address; }")
        await pg.wait_for_timeout(500); await shot("06-map-popup.png")
        # same session: roster opens without a prompt (key in sessionStorage)
        await pg.goto(BASE + "roster.html", wait_until="networkidle"); await pg.wait_for_timeout(1200)
        results["roster_prompted_again"] = await pg.evaluate("!!document.querySelector('.lock-overlay')")
        results["roster_count"] = await pg.inner_text("#count")
        await shot("07-roster-unlocked.png")
        await pg.goto(BASE + "index.html", wait_until="networkidle"); await pg.wait_for_timeout(800)
        await shot("08-overview-unlocked.png")
        # new session (fresh context) must be locked again
        ctx2 = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        pg2 = await ctx2.new_page()
        await pg2.goto(BASE + "roster.html", wait_until="networkidle"); await pg2.wait_for_selector(".lock-overlay")
        results["new_session_locked"] = True
        await pg2.screenshot(path=f"{OUT}/{PFX}09-mobile-lock.png")
        await pg2.fill("#lock-pw", PW); await pg2.click(".lock-card button[type=submit]")
        await pg2.wait_for_selector(".lock-overlay", state="detached", timeout=20000)
        await pg2.goto(BASE + "map.html", wait_until="networkidle"); await pg2.wait_for_timeout(1500)
        await pg2.screenshot(path=f"{OUT}/{PFX}10-mobile-map.png", full_page=True)
        await b.close()
        for k, v in results.items(): print(f"{k}: {v}")
        print("JS errors:", errors or "none")
asyncio.run(main())
