
import asyncio
import json
import os
import random
from datetime import datetime, timezone
from collections import defaultdict

from playwright.async_api import async_playwright, Error as PlaywrightError

from omar.scout import Scout
from omar.worker import AxiomWorker
from omar.analyst_engine import AnalysisDecision, DecisionType
from omar.human_browser import load_site_map
from omar.config import (
    MAX_CONCURRENT_WORKERS,
    DASHBOARD_DATA_FILE,
    AUTH_FILE,
    EJECTION_THRESHOLD,
)
from omar.auth_manager import AuthManager

class Director:
    def __init__(self):
        self.decision_queue = asyncio.Queue()
        self.workers = {}
        self.warning_counts = defaultdict(int)
        self.ejected_pairs = set()
        self.dashboard_data = {
            "system_status": "RUNNING",
            "monitored_pairs": [],
            "decisions": [],
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        self.human_sim_lock = asyncio.Lock()
        load_site_map()
        self.browser_context = None
        self.scout = None
        self.auth_manager = AuthManager()

    async def _handle_ejection_and_replacement(self, pair_to_eject: str):
        print(f"⚖️ DIRECTOR: Ejection threshold reached for {pair_to_eject}. Initiating ejection protocol.")
        
        # 1. Stop and remove the worker
        if pair_to_eject in self.workers:
            worker_instance = self.workers[pair_to_eject].get("instance")
            if worker_instance:
                worker_instance.stop()
            del self.workers[pair_to_eject]
        
        # 2. Add to temporary experience list (not a permanent blacklist)
        self.ejected_pairs.add(pair_to_eject)
        if pair_to_eject in self.warning_counts:
            del self.warning_counts[pair_to_eject]

        # Update dashboard
        self._update_monitored_list()
        print(f"   - Worker for {pair_to_eject} terminated.")

        # 3. Scout for a new opportunity, ignoring all currently active and recently ejected pairs
        print("   - DIRECTOR: Deploying Scout to find a replacement...")
        
        # The ignore list now includes both ejected and currently monitored pairs
        ignore_list = self.ejected_pairs.union(set(self.workers.keys()))
        
        if not self.scout:
             self.scout = Scout(self.browser_context)

        new_opportunities = await self.scout.find_opportunities(ignore_list=ignore_list)

        if new_opportunities:
            new_pair = new_opportunities[0]
            print(f"   + SCOUT: Found new candidate: {new_pair}")
            await self._deploy_worker(new_pair)
        else:
            print("   - SCOUT: Could not find a suitable replacement. A slot will remain open.")
        
        # The ejected pair is now removed from the ignore list for future scouting missions
        self.ejected_pairs.remove(pair_to_eject)

    async def _deploy_worker(self, pair: str):
        print(f"🚀 DIRECTOR: Deploying new Worker for {pair}")
        cmd_q = asyncio.Queue()
        worker = AxiomWorker(f"https://axiom.trade/trading/{pair}", self.browser_context, self.decision_queue, cmd_q)
        
        # Start the worker task
        worker_task = asyncio.create_task(worker.start())
        
        self.workers[pair] = {
            "status": "active", 
            "command_queue": cmd_q,
            "instance": worker, # Store the instance for graceful shutdown
            "task": worker_task # Store the task for cancellation
        }
        self._update_monitored_list()

    def _update_monitored_list(self):
        self.dashboard_data["monitored_pairs"] = [
            {"pair": p, "status": w.get("status", "unknown"), "warnings": self.warning_counts.get(p, 0)}
            for p, w in self.workers.items()
        ]
        self._write_dashboard_data()

    async def run(self):
        print("👑 DIRECTOR v3.1: Ejection Protocol ENABLED.")
        
        # Check authentication status first
        auth_status = self.auth_manager.get_auth_status()
        if not auth_status["exists"] or not auth_status["is_valid"]:
            print("⚠️ DIRECTOR: No valid authentication found. Please run the web interface and log in first.")
            self.dashboard_data["system_status"] = "STOPPED"
            self._write_dashboard_data()
            return
        
        print(f"🔐 DIRECTOR: Authentication valid - {auth_status['cookies_count']} cookies found")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
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
            self.browser_context = await browser.new_context(
                storage_state=AUTH_FILE if os.path.exists(AUTH_FILE) else None,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
            )
            self.scout = Scout(self.browser_context)
            
            print("🔭 DIRECTOR: Initializing with Scout mission...")
            # We don't want to start with pairs we've just ejected if we restart
            initial_ignore = self.ejected_pairs.copy()
            found_pairs = await self.scout.find_opportunities(ignore_list=initial_ignore)
            
            if not found_pairs:
                print("⚠️ DIRECTOR: No initial pairs found. Check auth.json or market conditions.")
                # We will just wait for decisions if any workers are running from a previous state (not implemented yet)
            
            # Initial deployment
            for pair in found_pairs[:MAX_CONCURRENT_WORKERS]:
                await self._deploy_worker(pair)

            # Main decision loop
            while True:
                decision = await self.decision_queue.get()
                pair = decision.pair_name
                
                if pair not in self.workers:
                    continue # Ignore decisions for workers that have been ejected

                print(f"📊 DIRECTOR: Received {decision.decision_type.value} for {pair}")
                self._log_decision(decision)

                # --- The Ejection Logic ---
                if decision.decision_type in [DecisionType.GO_IDLE, DecisionType.HIGH_RISK]:
                    self.warning_counts[pair] += 1
                    print(f"   - {pair} now has {self.warning_counts[pair]}/{EJECTION_THRESHOLD} warnings.")
                    
                    if self.warning_counts[pair] >= EJECTION_THRESHOLD:
                        await self._handle_ejection_and_replacement(pair)

                elif decision.decision_type == DecisionType.BUY_OPPORTUNITY:
                    if self.warning_counts[pair] > 0:
                        print(f"   - Redemption! {pair} has shown a BUY_OPPORTUNITY. Resetting warnings.")
                        self.warning_counts[pair] = 0
                
                self._update_monitored_list()

    def _log_decision(self, decision: AnalysisDecision):
        res = decision.__dict__.copy()
        res['decision_type'] = decision.decision_type.value
        self.dashboard_data["decisions"].insert(0, res)
        self.dashboard_data["decisions"] = self.dashboard_data["decisions"][:50]
        # self._write_dashboard_data() is called by _update_monitored_list

    def _write_dashboard_data(self):
        self.dashboard_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        temp_file_path = DASHBOARD_DATA_FILE + ".tmp"
        try:
            with open(temp_file_path, 'w') as f:
                json.dump(self.dashboard_data, f, indent=2, default=str)
            os.rename(temp_file_path, DASHBOARD_DATA_FILE)
        except (IOError, OSError) as e:
            print(f"DIRECTOR: Error writing dashboard data: {e}")

if __name__ == "__main__":
    if os.path.exists(DASHBOARD_DATA_FILE):
        os.remove(DASHBOARD_DATA_FILE)
    try:
        asyncio.run(Director().run())
    except KeyboardInterrupt:
        print("\nDIRECTOR: Shutting down gracefully.")

