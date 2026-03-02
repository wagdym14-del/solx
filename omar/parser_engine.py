
import re

# --- Parser Engine ---
# This module is responsible for taking raw, unstructured text scraped
# from the UI and turning it into structured, machine-readable data
# that the FinancialAnalyst can process.

class SwapParser:
    """
    Parses raw text strings from the Axiom swap list into structured data.
    """
    
    def __init__(self):
        # This regex is the "brain" of the parser. It uses named groups to find and extract
        # the different parts of the swap information.
        # Example string: "Buy 0.02 SOL $2.91 1m ago"
        self.swap_regex = re.compile(
            r"(?P<type>Buy|Sell)\s+"          # Match "Buy" or "Sell"
            r"(?P<amount_coin>[\d.,]+)\s+"      # Match the coin amount (e.g., "0.02")
            r"(?P<coin>\w+)\s+"               # Match the coin symbol (e.g., "SOL")
            r"\$(?P<amount_usd>[\d.,]+)\s+"     # Match the USD amount (e.g., "2.91")
            r"(?P<time_ago>.+? ago)"          # Match the time string (e.g., "1m ago")
        , re.IGNORECASE)

    def parse_swap_string(self, raw_text: str) -> dict | None:
        """
        Takes a single raw string and attempts to parse it into a structured dictionary.

        Args:
            raw_text: The string scraped from the UI, e.g., "Buy 0.02 SOL $2.91 1m ago"

        Returns:
            A dictionary with structured data, or None if the string doesn't match.
        """
        match = self.swap_regex.search(raw_text)

        if not match:
            # print(f"--> PARSER: Could not understand string: '{raw_text}'")
            return None

        data = match.groupdict()

        # --- Data Cleaning and Type Conversion ---
        try:
            data['type'] = data['type'].lower()
            data['amount_coin'] = float(data['amount_coin'].replace(',', ''))
            data['amount_usd'] = float(data['amount_usd'].replace(',', ''))
            # The 'coin' and 'time_ago' are already strings, so they are fine.
            
            # print(f"--> PARSER: Understood -> {data}")
            return data
        except (ValueError, KeyError) as e:
            print(f"--> PARSER ERROR: Could not clean data for '{raw_text}'. Reason: {e}")
            return None

# --- Example Usage (for testing) ---
if __name__ == "__main__":
    print("--- Testing Parser Engine ---")
    parser = SwapParser()

    test_strings = [
        "Buy 0.02 SOL $2.91 1m ago",
        "Sell 1,234.56 BTC $45,000.00 2h ago",
        "Buy 15.8 ETH $3,500.12 just now",
        "This is not a valid string",
        "Sell 0.5 SOL $75.20 5s ago and some other text"
    ]

    for text in test_strings:
        parsed_data = parser.parse_swap_string(text)
        if parsed_data:
            print(f"✅ Parsed '{text}' -> {parsed_data}")
        else:
            print(f"❌ Failed to parse '{text}'")

