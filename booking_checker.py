import time
import json
import nodriver as n
from datetime import datetime
from typing import Dict, Set

# Local imports (assuming these exist in your project structure)
from utils.logger import setup_logger

log = setup_logger(__name__)

async def get_all_manual_bookings(driver, course_value, course_display_name):
    """
    Retrieves all current bookings from the dashboard using nodriver.
    """
    log.debug(f"Retrieving all {course_display_name} bookings...")
    
    # ---------------------------------------------------------
    # 1. NAVIGATION & TAB RECOVERY
    # ---------------------------------------------------------
    try:
        tab = await driver.get("https://bookingportal.cdc.com.sg/NewPortal/Booking/Dashboard.aspx")
        if not tab: raise Exception("Tab is None")
    except:
        log.warning("driver.get() returned None. Searching open tabs...")
        tab = None
        for t in driver.tabs:
            if "Booking/Dashboard" in t.url:
                tab = t
                break
        if not tab: 
            tab = driver.main_tab

    # ---------------------------------------------------------
    # 2. LOGIN CHECK
    # ---------------------------------------------------------
    if "login" in tab.url.lower() or "signin" in tab.url.lower():
        log.critical("Redirected to Login Page! You are not logged in.")
        return []

    bookings = []

    try:
        # ---------------------------------------------------------
        # 3. WAIT FOR TABLE
        # ---------------------------------------------------------
        await tab.wait_for("#ctl00_ContentPlaceHolder1_gvBooked", timeout=15)

        # ---------------------------------------------------------
        # 4. ROBUST EXTRACTION (JSON Strategy)
        # ---------------------------------------------------------
        # We use the exact logic from test_extraction.py
        extraction_js = """
        (() => {
            const rows = Array.from(document.querySelectorAll('#ctl00_ContentPlaceHolder1_gvBooked tr'));
            
            const data = rows.map(row => {
                 const cells = row.querySelectorAll('td');
                 
                 // Filter out headers (which use <th>) or malformed rows
                 if (cells.length < 5) return null;
                 
                 // Return simple array: [Date, Session, Course]
                 return [
                     cells[0].innerText.trim(), 
                     cells[1].innerText.trim(), 
                     cells[4].innerText.trim()
                 ];
             }).filter(r => r !== null);

            return JSON.stringify(data);
        })();
        """
        
        # Get string data and parse it in Python
        json_str = await tab.evaluate(extraction_js)
        raw_rows = json.loads(json_str)

        log.debug(f"Parsed {len(raw_rows)} rows from dashboard.")

        for row in raw_rows:
            # row is ['Date', 'Session', 'Course']
            r_date, r_session, r_course = row[0], row[1], row[2]

            # Filter by Course Name
            if r_course != course_value:
                continue

            try:
                date_obj = datetime.strptime(r_date, "%d/%b/%Y")
                session_no = int(r_session)
                
                bookings.append({
                    "date": date_obj,
                    "session": session_no
                })
            except ValueError as ve:
                log.error(f"Failed to parse row {row}: {ve}")
                continue

        log.info(f"Retrieved {len(bookings)} {course_display_name} booking(s).")

    except Exception as e:
        log.error(f"Failed to retrieve bookings: {e}")
        try:
            await tab.save_screenshot("logs/error_dashboard.jpg")
        except:
            pass

    return bookings

def filter_practical_slots(slots, config, existing_bookings, bot):
    """
    Filters available slots based on user configuration.
    (Logic unchanged from your original version, just cleaned up)
    """
    t_start = time.perf_counter()

    filtered = []
    dates_with_a_found_slot = set()
    
    # Config extraction
    one_slot_per_day: bool = config.get("one_slot_per_day", False)
    excluded_dates: Set[str] = set(config.get("excluded_dates", []))
    non_peak_sessions: Set[int] = set(config.get("non_peak_sessions", {1, 3, 4}))
    
    allowed_sessions: Dict[str, Set[int]] = {
        day: set(sessions) for day, sessions in config.get("allowed_sessions", {}).items()
    }
    included_dates_sessions: Dict[str, Set[int]] = {
        date: set(sessions) for date, sessions in config.get("included_dates", {}).items()
    }

    booked_slots: Dict[str, int] = {
        b["date"].strftime("%Y-%m-%d"): b["session"] for b in existing_bookings
    }

    for slot in slots:
        slot_date_obj = datetime.strptime(slot["date"], "%d/%b/%Y").date()
        date_str = slot_date_obj.strftime("%Y-%m-%d")
        weekday = slot["dayname"][:3].upper()
        session = slot["session"]

        # 1. One slot per day check
        if one_slot_per_day and date_str in dates_with_a_found_slot:
            continue

        # 2. Check against existing bookings
        if date_str in booked_slots:
            booked_session = booked_slots[date_str]
            # Upgrade logic: Earlier, non-peak session
            if session < booked_session and session in non_peak_sessions:
                msg = (
                    f"Found an earlier non-peak slot on a booked date!\n"
                    f"Date: {slot_date_obj.strftime('%d %b %Y, %a')}\n"
                    f"New Slot: Session {session}\n"
                    f"Current Slot: Session {booked_session}\n\n"
                    f"Note: You must cancel your existing booking for this day before booking the new one."
                )
                log.debug(msg)
                bot.send(msg)
                filtered.append(slot)
                dates_with_a_found_slot.add(date_str)
                continue
            continue

        # 3. Included Dates (Overrides exclusions)
        if date_str in included_dates_sessions:
            if session in included_dates_sessions[date_str]:
                log.debug(f"MATCH (Included): {date_str} S{session}")
                filtered.append(slot)
                dates_with_a_found_slot.add(date_str)
            continue

        # 4. Excluded Dates
        if date_str in excluded_dates:
            continue

        # 5. Allowed Days/Sessions
        allowed_sessions_for_day = allowed_sessions.get(weekday, set())
        if not allowed_sessions_for_day or session not in allowed_sessions_for_day:
            continue

        # Valid Match
        log.debug(f"MATCH: {date_str} S{session}")
        filtered.append(slot)
        dates_with_a_found_slot.add(date_str)
        
    t_end = time.perf_counter()
    log.info(f"Filtered {len(slots)} slots down to {len(filtered)} in {(t_end - t_start) * 1000:.2f} ms.")

    return filtered


async def is_slot_confirmed(driver, target_date, target_session, course_value):
    """
    Verifies if a specific slot appears in the booked list.
    """
    try:
        # Re-use the same robust logic as get_all_manual_bookings
        bookings = await get_all_manual_bookings(driver, course_value, course_value) # display_name same as value for check
        
        for b in bookings:
            # Convert booking date to string to match target_date format (assuming dd/Mon/YYYY)
            # You might need to adjust format depending on what 'target_date' string looks like
            b_date_str = b["date"].strftime("%d/%b/%Y") 
            
            if b_date_str == target_date and b["session"] == target_session:
                return True
                
        return False

    except Exception as e:
        log.error(f"Confirmation check failed: {e}")
        return False