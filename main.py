import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash

from omar.scout import load_scout_criteria
from omar.config import AUTH_FILE, DASHBOARD_DATA_FILE
from omar.auth_manager import AuthManager


def create_app() -> Flask:
    app = Flask(__name__)
    # Simple dev secret key for flashing messages; replace in production.
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

    def _default_dashboard_data() -> dict:
        return {
            "system_status": "STOPPED",
            "monitored_pairs": [],
            "decisions": [],
            "market_entities": {},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def load_dashboard_data() -> dict:
        if os.path.exists(DASHBOARD_DATA_FILE):
            try:
                with open(DASHBOARD_DATA_FILE, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = _default_dashboard_data()
        else:
            data = _default_dashboard_data()

        # Ensure expected keys exist so the template doesn't break.
        if "market_entities" not in data:
            data["market_entities"] = {}
        if "monitored_pairs" not in data:
            data["monitored_pairs"] = []
        if "decisions" not in data:
            data["decisions"] = []
        if "system_status" not in data:
            data["system_status"] = "STOPPED"

        return data

    @app.get("/")
    def index():
        dashboard_data = load_dashboard_data()
        scout_config = load_scout_criteria()
        # Lightweight, read-only stats derived from dashboard_data.
        stats = {
            "monitored_pairs": len(dashboard_data.get("monitored_pairs", [])),
            "entities": len(dashboard_data.get("market_entities", {})),
            "decisions": len(dashboard_data.get("decisions", [])),
            "last_updated": dashboard_data.get("last_updated"),
        }
        # Derive authentication file status without modifying Director logic.
        auth_manager = AuthManager()
        auth_status = auth_manager.get_auth_status()
        auth_info = {
            "exists": auth_status["exists"],
            "last_updated": auth_status["last_updated"],
            "cookies_count": auth_status["cookies_count"],
            "is_valid": auth_status["is_valid"]
        }

        return render_template(
            "index.html",
            data=dashboard_data,
            scout_config=scout_config,
            stats=stats,
            auth_info=auth_info,
        )

    @app.post("/config")
    def update_config():
        try:
            max_age_minutes = int(request.form.get("max_age_minutes", 60))
            min_holders = int(request.form.get("min_holders", 100))
            trending_timeframe = request.form.get("trending_timeframe", "30m")
            top_n = int(request.form.get("top_n", 10))
        except ValueError:
            flash("Invalid numeric values in Scout configuration.", "error")
            return redirect(url_for("index"))

        new_config = {
            "max_age_minutes": max_age_minutes,
            "min_holders": min_holders,
            "trending_timeframe": trending_timeframe,
            "top_n": top_n,
        }

        try:
            with open("scout_config.json", "w") as f:
                json.dump(new_config, f, indent=2)
            flash("Scout configuration updated successfully.", "success")
        except OSError as e:
            flash(f"Failed to write scout_config.json: {e}", "error")

        return redirect(url_for("index"))

    @app.post("/save-auth")
    def save_auth():
        """
        Legacy endpoint: allows pasting raw auth JSON.
        Kept for compatibility, even though the UI now prefers manual login.
        """
        raw = (request.form.get("auth_data") or "").strip()
        if not raw:
            flash("No authentication data provided.", "error")
            return redirect(url_for("index"))

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            flash(f"Invalid JSON: {e}", "error")
            return redirect(url_for("index"))

        try:
            with open(AUTH_FILE, "w") as f:
                json.dump(data, f, indent=2)
            flash("Authentication data saved successfully.", "success")
        except OSError as e:
            flash(f"Failed to save authentication data: {e}", "error")

        return redirect(url_for("index"))

    def _run_manual_login_flow():
        """
        Opens a separate Playwright browser window so the user can log in manually.
        When the window is closed (or the timeout elapses), the storage state is
        saved to AUTH_FILE for reuse by the Director.
        """
        import asyncio
        from playwright.async_api import async_playwright
        from omar.auth_manager import AuthManager

        async def _inner():
            # Check if Playwright browsers are installed
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    # Try to launch browser to check installation
                    test_browser = await p.chromium.launch(headless=True)
                    await test_browser.close()
            except Exception as e:
                print(f"[manual_login] Playwright browser check failed: {e}")
                print(f"[manual_login] Please run: python3 -m playwright install chromium")
                return
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-web-security',
                        '--disable-features=VizDisplayCompositor',
                        '--ignore-certificate-errors',
                        '--ignore-ssl-errors',
                        '--ignore-certificate-errors-spki-list',
                        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    ]
                )
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    extra_http_headers={
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    }
                )
                page = await context.new_page()
                await page.goto("https://axiom.trade", wait_until="domcontentloaded")

                # Allow ample time for manual login; user can close the window earlier.
                total_wait_seconds = 15 * 60
                elapsed = 0
                interval = 2
                while elapsed < total_wait_seconds and not page.is_closed():
                    await asyncio.sleep(interval)
                    elapsed += interval

                try:
                    print(f"[manual_login] Saving authentication state to {AUTH_FILE}...")
                    await context.storage_state(path=AUTH_FILE)
                    print(f"[manual_login] Authentication state saved successfully!")
                    
                    # Enhanced validation using AuthManager
                    auth_manager = AuthManager()
                    auth_manager.refresh_auth_data()
                    
                    if auth_manager.validate_auth_data():
                        status = auth_manager.get_auth_status()
                        print(f"[manual_login] ✅ Authentication validated!")
                        print(f"[manual_login] 📊 Cookies: {status['cookies_count']}")
                        print(f"[manual_login] 🔐 Valid session: {status['has_session']}")
                        print(f"[manual_login] 🌐 Domains: {', '.join(status['domains'])}")
                        
                        # Create backup for safety
                        auth_manager.backup_auth_data()
                        
                        # Clean up expired cookies
                        cleaned = auth_manager.cleanup_expired_cookies()
                        if cleaned > 0:
                            print(f"[manual_login] 🧹 Cleaned {cleaned} expired cookies")
                    else:
                        print(f"[manual_login] ❌ Authentication validation failed!")
                        
                except Exception as save_error:
                    print(f"[manual_login] Error saving authentication state: {save_error}")
                finally:
                    await browser.close()

        try:
            asyncio.run(_inner())
        except Exception as e:
            # We can't flash from this thread, so just log to stderr.
            print(f"[manual_login] Error during manual login flow: {e}")

    @app.post("/open-login-browser")
    def open_login_browser():
        """
        Spawns a background task that opens a private browser window for manual login.
        """
        try:
            thread = threading.Thread(target=_run_manual_login_flow, daemon=True)
            thread.start()
            flash("Login browser opened. Complete login in the new window; cookies will be saved automatically.", "success")
        except Exception as e:
            flash(f"Failed to open login browser: {str(e)}", "error")
            print(f"[main] Error starting login browser thread: {e}")
        return redirect(url_for("index"))

    return app


app = create_app()


if __name__ == "__main__":
    # For local development / debugging.
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

