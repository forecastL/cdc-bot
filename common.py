import random
import time
import csv
import asyncio
from datetime import datetime
from os.path import exists
from utils.logger import setup_logger

log = setup_logger(__name__)

# sleep function for random delay
async def sleep_random(refresh_mode, backoff_multiplier=1.0):
    """
    Sleep with random delays based on current mode.
    Applies backoff multiplier to slow down when hitting rate limits.
    """
    if refresh_mode.in_aggressive():
        delay = random.uniform(2, 4)  # Increased from 3-5
        log.debug(f"Aggressive mode: base sleep {delay:.2f}s")
    elif refresh_mode.in_probe():
        delay = random.uniform(5, 9)  # Increased from 2-4
        log.debug(f"Probe mode: base sleep {delay:.2f}s")
    else:
        delay = random.uniform(13, 40)  # Increased from 15-24
        log.debug(f"Normal mode: base sleep {delay:.2f}s")
    
    actual_delay = delay * backoff_multiplier
    if backoff_multiplier > 1.0:
        log.info(f"Applying {backoff_multiplier:.2f}x backoff: sleeping {actual_delay:.2f}s")
    
    await asyncio.sleep(actual_delay)

async def cloudflare_handler(tab, bot):
    log.debug("Checking for Cloudflare challenge page...")
    if await is_cloudflare_challenge_page(tab, bot):
        if not await wait_for_cloudflare_challenge_to_clear(tab):
            await tab.verify_cf()
            log.info("Verified Cloudflare challenge. Continuing...")
        

# cloudflare detection function  
async def is_cloudflare_challenge_page(tab, bot):
    try:
        # nodriver: evaluate document.title
        title = await tab.evaluate("document.title")
        if title and "just a moment" in title.lower():
            return True
        return False
    
    except Exception as e:
        log.error(f"Error detecting Cloudflare challenge page: {e}")
        return False


async def wait_for_cloudflare_challenge_to_clear(tab, timeout=15, log_path="logs/cf_wait_log.csv"):
    """
    Waits up to `timeout` seconds for the Cloudflare challenge to disappear.
    Logs duration and outcome in CSV format for tuning.
    Returns True if cleared automatically, False if not.
    """
    start_time = time.time()
    log.info(f"Waiting up to {timeout}s for Cloudflare challenge to clear...")

    while time.time() - start_time < timeout:
        if not await is_cloudflare_challenge_page(tab, bot=None):
            duration = round(time.time() - start_time, 2)
            log.info(f"Cloudflare challenge cleared after {duration:.2f}s.")
            log_cloudflare_wait_csv(duration, success=True, log_path=log_path)
            return True
        await asyncio.sleep(0.5)

    duration = round(time.time() - start_time, 2)
    log.error(f"Cloudflare challenge did NOT clear after {duration:.2f}s.")
    log_cloudflare_wait_csv(duration, success=False, log_path=log_path)
    return False

def log_cloudflare_wait_csv(duration, success, log_path):
    """
    Logs Cloudflare wait data in CSV format:
    timestamp, outcome, duration
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outcome = "CLEARED" if success else "TIMEOUT"
    header = ["timestamp", "outcome", "duration_s"]

    # Write header if file doesn't exist
    write_header = not exists(log_path)
    with open(log_path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(header)
        writer.writerow([timestamp, outcome, duration])
        log.debug(f"Logged Cloudflare wait: {timestamp}, {outcome}, {duration}s to {log_path}")
    
async def wait_for_elem(tab, value, timeout=10.0):
    try:
        return await tab.wait_for(selector=f"#{value}", timeout=timeout)
    except Exception as e:
        raise

async def anonymize_fields(tab):
    anon_map = {
        "ctl00_HeaderSub_lblName": "ADMINISTRATOR",
        "ctl00_HeaderSub_lblUserID": "XXXXXXXX",
        "ctl00_HeaderSub_lblNRIC": "XXXXXXXXX",
        "ctl00_HeaderSub_lblExpiryDate": "XX/XX/XXXX",
        # "ctl00_HeaderSub_lblStoreValue": "$XXX.XX",
        "ctl00_HeaderSub_lblDeposit": "$XXX.XX"
    }

    log.debug(f"Anonymizing fields in the booking portal called at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for elem_id, fake_text in anon_map.items():
        script = f"document.getElementById('{elem_id}').innerText = '{fake_text}';"
        try:
            await tab.evaluate(script)
        except Exception:
            pass # Element might not exist