
# --- The Smart Scout (v3.4: Sequential Trend-Filter Explorer) ---

import asyncio
import json
import os
import random
from typing import Set
from playwright.async_api import BrowserContext, Page, Locator, expect, Error

# --- Intelligence Components ---
from omar.human_browser import human_goto, recall_selector, remember_selector, forget_selector

# --- Scout Configuration Loader ---
CONFIG_FILE = "scout_config.json"

def load_scout_criteria():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    # Default configuration now uses the new sequential trending strategy
    return {
        "max_age_minutes": 60,
        "min_holders": 100,
        "trending_timeframe": "30m", # New key for the timeframe button
        "top_n": 10 
    }

# --- Memory-Driven Action Helper ---
async def try_action(page: Page, action_name: str, fallback_locator: Locator, click: bool = True):
    selector = recall_selector(action_name)
    element_found = False
    
    if selector:
        try:
            await expect(page.locator(selector)).to_be_visible(timeout=5000)
            if click: await page.locator(selector).click()
            element_found = True
        except Error:
            print(f"   ❌ MEMORY MISS: Selector for '{action_name}' failed. Forgetting it.")
            forget_selector(action_name)
            element_found = False

    if not element_found:
        try:
            await expect(fallback_locator).to_be_visible(timeout=10000)
            if click: 
                await fallback_locator.click()
                try:
                    handle = await fallback_locator.element_handle()
                    selector_string = await handle.evaluate("el => window.playwright.selector(el)")
                    if selector_string:
                        remember_selector(action_name, selector_string)
                        print(f"   🧠 MEMORY GAIN: Learned new selector for '{action_name}'.")
                except Exception:
                    pass # Fallback worked, but couldn't learn a selector.
            return True
        except Exception as e:
            print(f"   🔥 Fallback for '{action_name}' FAILED: {e}")
            return False
    return True


# --- The Scout Class (Upgraded to v3.4) ---

class Scout:
    """
    Scout v3.4 implements a sequential strategy:
    1. Selects the 'Trending' tab.
    2. Clicks the desired timeframe (e.g., '30m').
    3. Applies additional filters (age, holders).
    """

    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Page | None = None
        self.criteria = load_scout_criteria()
        self.discover_url = "https://axiom.trade/discover"

    async def _add_human_like_noise(self, duration_seconds: int):
        if not self.page or self.page.is_closed(): return
        end_time = asyncio.get_event_loop().time() + duration_seconds
        while asyncio.get_event_loop().time() < end_time:
            await asyncio.sleep(random.uniform(1, 4))

    async def find_opportunities(self, ignore_list: Set[str] | None = None) -> list[str]:
        print(f"🔭 SCOUT v3.4: Sequential Trend-Filter mission. Criteria: {self.criteria}")
        if ignore_list:
             print(f"   - Ignoring {len(ignore_list)} previously known pairs.")

        try:
            self.page = await self.context.new_page()
            await human_goto(self.page, self.discover_url)

            # --- SEQUENTIAL STRATEGY (v3.4) ---

            # 1. Click the main 'Trending' tab
            trending_tab_locator = self.page.get_by_role("button", name="Trending", exact=True)
            if not await try_action(self.page, "scout_main_trending_tab", trending_tab_locator):
                raise Exception("Could not click the main 'Trending' tab.")
            await expect(self.page.locator("div.animate-spin")).to_be_hidden(timeout=30000)
            print("   - SCOUT: Step 1/4 - Switched to 'Trending' tab.")

            # 2. Click the desired timeframe button (e.g., '30m')
            timeframe = self.criteria['trending_timeframe']
            timeframe_button_locator = self.page.get_by_role("button", name=timeframe, exact=True)
            if not await try_action(self.page, f"scout_timeframe_{timeframe}", timeframe_button_locator):
                raise Exception(f"Could not click the '{timeframe}' button.")
            await expect(self.page.locator("div.animate-spin")).to_be_hidden(timeout=30000)
            print(f"   - SCOUT: Step 2/4 - Set timeframe to '{timeframe}'.")

            # 3. Open the filter panel
            if not await try_action(self.page, "scout_filter_button", self.page.get_by_role("button", name="Filter")):
                raise Exception("Could not open filter panel.")
            print("   - SCOUT: Step 3/4 - Opened filter panel.")

            # Ensure panel is visible before proceeding
            filter_panel_locator = self.page.locator(recall_selector("scout_filter_panel") or "div.bg-bg-primary.border.border-border-primary.rounded-lg")
            await expect(filter_panel_locator).to_be_visible(timeout=10000)

            # 4. Apply additional filters inside the panel
            await filter_panel_locator.locator('input[placeholder="Max"]').fill(f"{self.criteria['max_age_minutes']}m")
            await try_action(self.page, "scout_metrics_button", filter_panel_locator.get_by_role("button", name="Metrics"))
            await filter_panel_locator.locator('input[placeholder="Min"]').nth(1).fill(str(self.criteria['min_holders']))
            
            await try_action(self.page, "scout_apply_all_button", filter_panel_locator.get_by_role("button", name="Apply All"))
            await expect(self.page.locator("div.animate-spin")).to_be_hidden(timeout=30000)
            print("   - SCOUT: Step 4/4 - Applied additional filters.")

            # --- EXTRACTION LOGIC (Unchanged) ---
            await self._add_human_like_noise(random.randint(3, 5))
            
            links_selector = recall_selector("scout_pair_links") or "a[href*='/trading/']"
            pair_links = self.page.locator(links_selector)
            count = await pair_links.count()
            
            if count == 0:
                print("   - SCOUT: No opportunities found after applying all criteria.")
                return []

            limit = min(count, self.criteria['top_n'])
            hrefs = await asyncio.gather(*[pair_links.nth(i).get_attribute('href') for i in range(limit)])
            extracted_pairs = [h.split('/')[-1] for h in hrefs if h]

            if ignore_list:
                original_count = len(extracted_pairs)
                extracted_pairs = [p for p in extracted_pairs if p not in ignore_list]
                if (filtered_count := original_count - len(extracted_pairs)) > 0:
                    print(f"   - SCOUT: Filtered out {filtered_count} known pairs from results.")

            print(f"🔭 SCOUT: Mission complete. Found {len(extracted_pairs)} new opportunities.")
            return extracted_pairs

        except Exception as e:
            if not isinstance(e, asyncio.CancelledError): print(f"🔥 SCOUT: CRITICAL ERROR: {e}")
            return []
        finally:
            if self.page and not self.page.is_closed():
                try: await self.page.close()
                except Error: pass
