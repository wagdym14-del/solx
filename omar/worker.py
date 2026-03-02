import asyncio
import random
import collections
from datetime import datetime, timezone
from playwright.async_api import Page, BrowserContext, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from omar.human_browser import human_goto, investigate_and_remember_swaps, get_best_row_selector
from omar.analyst_engine import FinancialAnalyst, DecisionType

# --- CONFIGURATION FOR BATCH ANALYSIS ---
MIN_SWAP_BATCH_SIZE = 25
MAX_SWAP_BATCH_SIZE = 50
BATCH_TIMEOUT_SECONDS = 8

class AxiomWorker:
    def __init__(self, task_url: str, browser_context: BrowserContext, decision_queue: asyncio.Queue, command_queue: asyncio.Queue):
        self.pair_name = task_url.split('/')[-1]
        self.task_url = task_url
        self.context = browser_context
        self.decision_queue = decision_queue
        self.command_queue = command_queue
        self.page: Page | None = None
        self.main_task = None # To hold the main task
        self._stop_event = asyncio.Event()
        self.status = "active"
        self.transaction_memory = collections.deque(maxlen=1000)
        self.analyst = FinancialAnalyst(pair_name=self.pair_name)
        self.swap_buffer = []
        self.last_analysis_time = datetime.now(timezone.utc)

    async def _handle_commands(self):
        if not self.command_queue.empty():
            cmd = await self.command_queue.get()
            if cmd.get("action") == "PERFORM_HUMAN_ACTION" and self.page and not self.page.is_closed():
                print(f"Worker ({self.pair_name}): Performing human-like scroll.")
                await self.page.mouse.wheel(0, random.randint(-200, 200))

    async def _flush_buffer_and_analyze(self):
        """Sends the content of the swap buffer to the analyst and clears it."""
        if not self.swap_buffer:
             # If there's nothing in the buffer, we still need to tell the analyst
             # that a cycle has passed with no activity.
            print(f"Worker ({self.pair_name}): Reporting no new activity to analyst.")
            decisions = self.analyst.run_full_analysis([])
        else:
            print(f"Worker ({self.pair_name}): Flushing {len(self.swap_buffer)} swaps to analyst.")
            decisions = self.analyst.run_full_analysis(self.swap_buffer)

        for decision in decisions:
            await self.decision_queue.put(decision)
        
        self.swap_buffer = []
        self.last_analysis_time = datetime.now(timezone.utc)

    async def start(self):
        self.main_task = asyncio.current_task()
        print(f"Worker for {self.pair_name}: Waking up...")
        try:
            self.page = await self.context.new_page()
            await human_goto(self.page, self.task_url)
            print(f"Worker ({self.pair_name}): Analysis loop now uses dynamic selectors and data batching.")

            while not self._stop_event.is_set():
                try:
                    best_selector = get_best_row_selector()
                    await self.page.evaluate(f'(selector) => {{ window.lastKnownRowCount = document.querySelectorAll(selector).length; }}', best_selector)

                    js_predicate = f'''(selector) => {{ 
                        const currentCount = document.querySelectorAll(selector).length;
                        return currentCount !== window.lastKnownRowCount;
                    }}'''

                    wait_for_data_task = asyncio.create_task(
                        self.page.wait_for_function(js_predicate, best_selector, timeout=30000) # Reduced timeout
                    )
                    handle_commands_task = asyncio.create_task(self._handle_commands())

                    done, pending = await asyncio.wait([wait_for_data_task, handle_commands_task], return_when=asyncio.FIRST_COMPLETED)

                    for task in pending: task.cancel()

                    if wait_for_data_task in done:
                        swaps = await investigate_and_remember_swaps(self.page, self.transaction_memory)
                        if swaps:
                            self.swap_buffer.extend(swaps)

                    time_since_last_analysis = (datetime.now(timezone.utc) - self.last_analysis_time).total_seconds()
                    buffer_size = len(self.swap_buffer)

                    if buffer_size >= MAX_SWAP_BATCH_SIZE or \
                       (buffer_size >= MIN_SWAP_BATCH_SIZE and time_since_last_analysis >= BATCH_TIMEOUT_SECONDS):
                        await self._flush_buffer_and_analyze()
                    
                except PlaywrightTimeoutError:
                    # This block is now the primary mechanism for signaling inactivity.
                    print(f"Worker ({self.pair_name}): DOM wait timed out. Checking for analysis flush.")
                    await self._handle_commands() 

                    # If enough time has passed, flush whatever is in the buffer,
                    # OR send an empty list to signal an idle cycle.
                    if (datetime.now(timezone.utc) - self.last_analysis_time).total_seconds() > BATCH_TIMEOUT_SECONDS:
                        await self._flush_buffer_and_analyze()
                    continue

                except Exception as e:
                    print(f"Minor error in worker loop for {self.pair_name}: {e}")
                    await asyncio.sleep(5)

        except Exception as e:
            print(f"CRITICAL Worker Error ({self.pair_name}): {e}")
            self.status = "failed"
        finally:
            if self.page and not self.page.is_closed():
                await self.page.close()
            print(f"Worker for {self.pair_name}: Shutting down.")

    def stop(self):
        self._stop_event.set()
        if self.main_task:
             self.main_task.cancel()