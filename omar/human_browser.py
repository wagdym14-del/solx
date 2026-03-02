
import asyncio
import json
import os
import random
from collections import deque
from playwright.async_api import Page, Locator

# --- Constants ---
SITE_MAP_FILE = "omar/site_map.json"
DEFAULT_ROWS_SELECTOR = 'div[role="row"]:has(div[role="gridcell"])'

# --- Spatial Memory Management ---
site_map = {}

def load_site_map():
    """Loads the site map from the JSON file into a global variable."""
    global site_map
    if os.path.exists(SITE_MAP_FILE):
        with open(SITE_MAP_FILE, 'r') as f:
            site_map = json.load(f)
    print("   🧠 SPATIAL MEMORY: Site map loaded.")

def save_site_map():
    """Saves the global site map variable back to the JSON file."""
    os.makedirs(os.path.dirname(SITE_MAP_FILE), exist_ok=True)
    with open(SITE_MAP_FILE, 'w') as f:
        json.dump(site_map, f, indent=4)
    print("   💾 SPATIAL MEMORY: Site map saved.")

def remember_selector(name: str, selector: str | dict):
    """Remembers a successful selector or a map in the site map."""
    if site_map.get(name) != selector:
        print(f"   ✨ SPATIAL MEMORY: Learning new selector/map for '{name}'.")
        site_map[name] = selector
        save_site_map()

def recall_selector(name: str) -> str | dict | None:
    """Recalls a selector or a map from the site map."""
    selector = site_map.get(name)
    if selector:
        print(f"   🧠 SPATIAL MEMORY: Recalled selector/map for '{name}'.")
    return selector

def forget_selector(name: str):
    """Forgets a selector or a map if it proves to be invalid."""
    if name in site_map:
        print(f"   🗑️ SPATIAL MEMORY: Forgetting invalid selector/map for '{name}'.")
        del site_map[name]
        save_site_map()

# --- NEW PUBLIC FUNCTION: The Source of Truth ---
def get_best_row_selector() -> str:
    """Gets the best-known row selector from memory, or returns the default."""
    return recall_selector("swaps_table_row_selector") or DEFAULT_ROWS_SELECTOR

# Load the map when the module is imported
load_site_map()

# --- Core Human-like Browser Interactions ---

async def human_goto(page: Page, url: str):
    """Navigates to a URL in a human-like manner."""
    print(f"   -> Navigating to {url}...")
    
    # Remove automation indicators
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
        
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
        
        window.chrome = {
            runtime: {},
        };
        
        Object.defineProperty(navigator, 'permissions', {
            get: () => ({
                query: () => Promise.resolve({ state: 'granted' }),
            }),
        });
    """)
    
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(random.uniform(2, 4))
    print(f"   ✓ Arrived at page.")

async def human_click(page: Page, selector: str):
    """Moves the mouse realistically and clicks an element."""
    await page.locator(selector).hover()
    await asyncio.sleep(random.uniform(0.2, 0.5))
    await page.locator(selector).click()

# --- The Intelligent Investigator (Upgraded with Column Mapping) ---

async def _identify_cell_content(cell: Locator) -> dict | None:
    """Applies heuristic theories to a single table cell to deduce its content."""
    link_element = cell.locator('a[href*="solscan.io"], a[href*="explorer.solana.com"]')
    if await link_element.count() > 0:
        try:
            href = await link_element.get_attribute('href')
            trader_address_text = await link_element.text_content()
            if href and trader_address_text:
                return {"type": "trader_info", "value": {"explorer_link": href, "trader_address": trader_address_text.strip()}}
        except Exception: return None

    text_content = await cell.text_content()
    if not text_content: return None
    text = text_content.strip()
    if text.startswith('$'):
        try:
            usd_value = float(text.replace('$', '').replace(',', ''))
            return {"type": "total_usd", "value": usd_value}
        except (ValueError, TypeError): return None
    if text.lower() in ['buy', 'sell']:
        return {"type": "trade_type", "value": text.lower()}
    if text.replace('.', '', 1).isdigit():
        try:
            return {"type": "amount", "value": float(text)}
        except (ValueError, TypeError): return None

    return None

async def _learn_column_map(row: Locator) -> dict:
    """Analyzes a single row to create a map of its column structure."""
    print("   🎓 LEARNING MODE: Analyzing a row to build column map...")
    column_map = {}
    cells = row.locator('div[role="gridcell"]')
    cell_count = await cells.count()
    for i in range(cell_count):
        cell = cells.nth(i)
        identification = await _identify_cell_content(cell)
        if identification:
            column_selector = f'div[role="gridcell"]:nth-child({i + 1})'
            if identification['type'] == 'trader_info':
                 if 'trader_info' not in column_map:
                    column_map['trader_info'] = {}
                 column_map['trader_info']['explorer_link'] = f'{column_selector} a'
                 column_map['trader_info']['trader_address'] = f'{column_selector} a'
            else:
                column_map[identification['type']] = column_selector
    
    if 'total_usd' in column_map and 'trade_type' in column_map:
        remember_selector("column_map", column_map)
        return column_map
    return {}


async def _extract_data_with_map(row: Locator, column_map: dict) -> dict:
    """Extracts data from a row using a pre-learned column map."""
    dissected_row_data = {}
    for data_type, selector in column_map.items():
        if data_type == 'trader_info':
            try:
                link_selector = selector['explorer_link']
                dissected_row_data['explorer_link'] = await row.locator(link_selector).get_attribute('href')
                dissected_row_data['trader_address'] = (await row.locator(link_selector).text_content() or "").strip()
            except Exception:
                return {} # Return empty to signal a map failure
        else:
            try:
                text_content = await row.locator(selector).text_content()
                if not text_content: 
                    return {} # Failure
                
                text = text_content.strip()
                if data_type == 'total_usd':
                    dissected_row_data[data_type] = float(text.replace('$', '').replace(',', ''))
                elif data_type == 'trade_type':
                     dissected_row_data[data_type] = text.lower()
                elif data_type == 'amount':
                    dissected_row_data[data_type] = float(text)

            except Exception:
                return {} # Failure
    return dissected_row_data


async def investigate_and_remember_swaps(page: Page, memory: set) -> list:
    """
    Intelligently dissects the trades table using Spatial Memory and Column Mapping.
    """
    print("   🕵️ INVESTIGATOR: Scanning trade list with advanced memory...")
    newly_found_swaps = []
    
    swaps_row_selector = get_best_row_selector()
    
    trade_rows = page.locator(swaps_row_selector)
    row_count = await trade_rows.count()

    if row_count == 0:
        if swaps_row_selector != DEFAULT_ROWS_SELECTOR:
            forget_selector("swaps_table_row_selector")
        print("   INVESTIGATION FAILED: Could not find any trade rows.")
        return []

    remember_selector("swaps_table_row_selector", swaps_row_selector)
    print(f"   ✓ Found {row_count} rows using selector: {swaps_row_selector}")

    column_map = recall_selector("column_map")

    if not column_map:
        column_map = await _learn_column_map(trade_rows.first)
        if not column_map:
            print("   ❌ LEARNING FAILED: Could not build a column map. Check selectors.")
            return []

    for i in range(row_count):
        row = trade_rows.nth(i)
        dissected_row_data = await _extract_data_with_map(row, column_map)

        if not dissected_row_data or 'explorer_link' not in dissected_row_data:
             print("   - Map extraction failed. Forgetting column map and re-learning on next run.")
             forget_selector("column_map")
             continue

        unique_id = dissected_row_data['explorer_link']
        if unique_id and unique_id not in memory:
            memory.add(unique_id)
            final_swap_data = {
                "type": dissected_row_data.get('trade_type', 'unknown'),
                "total_usd": dissected_row_data.get('total_usd', 0.0),
                "trader_address": dissected_row_data.get('trader_address', 'unknown'),
                "explorer_link": unique_id,
            }
            if final_swap_data['type'] != 'unknown' and final_swap_data['trader_address'] != 'unknown':
                newly_found_swaps.append(final_swap_data)

    if newly_found_swaps:
        print(f"   -> Successfully identified {len(newly_found_swaps)} new transaction(s) using column map.")
        
    return newly_found_swaps
