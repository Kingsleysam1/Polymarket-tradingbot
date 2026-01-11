
import logging
from py_clob_client.client import ClobClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def debug_pagination():
    client = ClobClient("https://clob.polymarket.com")
    
    # Test 1: Try passing active=True
    try:
        logger.info("Test 1: calling get_simplified_markets(active=True, closed=False)...")
        # Passing unexpected kwargs might error or be ignored
        resp = client.get_simplified_markets(active=True, closed=False)
        data = resp.get("data", [])
        open_ones = [m for m in data if m.get("active") and not m.get("closed")]
        logger.info(f"Test 1 Results: {len(open_ones)} open markets found in first batch")
    except Exception as e:
        logger.info(f"Test 1 failed: {e}")

    # Test 2: Pagination Loop
    logger.info("\nTest 2: Looping through pages...")
    next_cursor = ""
    page = 0
    max_pages = 10
    
    while page < max_pages:
        page += 1
        logger.info(f"Fetching page {page} (cursor={next_cursor})...")
        
        try:
            resp = client.get_simplified_markets(next_cursor=next_cursor)
            data = resp.get("data", [])
            next_cursor = resp.get("next_cursor", "")
            
            open_ones = [m for m in data if m.get("active") and not m.get("closed")]
            if open_ones:
                logger.info(f"SUCCESS! Found {len(open_ones)} open markets on page {page}")
                for m in open_ones[:5]:
                    print(f"ID: {m.get('condition_id')} (Need to fetch details for name)")
                return
            
            if not next_cursor or next_cursor == "MA==": # Basic check, might need robust check
                if page > 1:
                    logger.info("End of pagination reached.")
                    break
                    
        except Exception as e:
            logger.error(f"Error on page {page}: {e}")
            break
            
    logger.info("Failed to find open markets in first 10 pages.")

if __name__ == "__main__":
    debug_pagination()
