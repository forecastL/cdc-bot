import json
from website.driver import get_driver
from website.login import LoginManager
from website.lesson_handler import LessonHandler
from website.booking_checker import filter_practical_slots, is_slot_confirmed, get_all_manual_bookings
from utils.telegram import TelegramBot
from utils.common import sleep_random, anonymize_fields, cloudflare_handler
from utils.logger import setup_logger  
from utils.refreshmode import RefreshMode
from datetime import datetime
from dotenv import load_dotenv
import os
import time
import yaml
import asyncio

def load_config():
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

async def open_practical_safe(parser, driver, bot):
    await parser.open_practical_booking_page()
    await cloudflare_handler(driver, bot)

def send_start_message(config, value, bot, all_manual_bookings=None):
    formatted = datetime.now().strftime("%d/%b/%Y %H:%M:%S")

    course_config = config['course']

    # Format allowed sessions
    allowed_sessions = ""
    for day, sessions in config.get("allowed_sessions", {}).items():
        allowed_sessions += f"  {day}: {', '.join(str(s) for s in sessions)}\n"

    allowed_dates = ""
    for date_str, sessions in config.get("included_dates", {}).items():
        allowed_dates += f"  {date_str}: {', '.join(str(s) for s in sessions)}\n"

    excluded_dates = ""
    for date_str, sessions in config.get("excluded_dates", {}).items():
        excluded_dates += f"  {date_str}: {', '.join(str(s) for s in sessions)}\n"

    # Format booked sessions
    booked_msg = f"Your booked {course_config['display_name']} sessions:\n"
    if all_manual_bookings:
        for booking in sorted(all_manual_bookings, key=lambda x: (x["date"], x["session"])):
            booked_msg += f"  - {booking['date'].strftime('%d/%b/%Y')} — Session {booking['session']}\n"
    else:
        booked_msg += " None booked yet.\n"

    # Session cost estimation
    non_peak = value // 73.03
    peak = value // 81.75

    msg = (
        f"🤖 Bot started at {formatted}\n"
        f"AutoBook: {'Enabled' if config['auto_book'] else 'Disabled'}\n"
        f"Course: {course_config['display_name']}\n"
        f"Current store value: {value}\n"
        f"Slots you can afford:\n"
        f"  - {non_peak:.0f} non-peak sessions\n"
        f"  - {peak:.0f} peak sessions\n\n"
        f"Allowed Sessions:\n{allowed_sessions}\n"
        f"Additional Included Dates:\n{allowed_dates}\n"
        f"Excluded Dates:\n{excluded_dates}\n"
        f"{booked_msg}\n"
        "📅 CDC Practical Session Timings:\n"
        "  Session 1: 08:30 - 10:10 (Non-peak)\n"
        "  Session 2: 10:20 - 12:00 (Peak)\n"
        "  Session 3: 12:45 - 14:25 (Non-peak)\n"
        "  Session 4: 14:35 - 16:15 (Non-peak)\n"
        "  Session 5: 16:25 - 18:05 (Peak)\n"
        "  Session 6: 18:50 - 20:30 (Peak)\n"
        "  Session 7: 20:40 - 22:20 (Peak)"
    )

    bot.send(msg, False)
    return msg

async def main():
    log = setup_logger(__name__)

    load_dotenv()

    config = load_config()
    course_config = config['course']
    dry_run = config.get("dry_run", False)
    
    browser = await get_driver(headless=config["headless"])
    tab = await browser.get("about:blank") # Get a tab to work with

    bot = TelegramBot(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))
    login = LoginManager(tab, username = os.getenv("CDC_USERNAME"), password = os.getenv("CDC_PASSWORD"), bot=bot)
    parser = LessonHandler(tab, course_config['value'], course_config['display_name'], "smd", bot)
    refresh_mode = RefreshMode()
    auto_book = config.get("auto_book", False)
    value_check = config.get("value_check", True)

    log.info("Starting script after loading configuration and environment variables.")
    
    cloudflare_count = 0
    backoff_multiplier = 1.0

    try:
        if await login.login():
            log.info(f"Login successful for user: {os.getenv('CDC_USERNAME')}")

            await cloudflare_handler(tab, bot) # handle cloudflare

            await tab.get("https://bookingportal.cdc.com.sg/NewPortal/Booking/Dashboard.aspx")

            await cloudflare_handler(tab, bot) # handle cloudflare

            all_manual_bookings = await get_all_manual_bookings(tab, course_config['name'], course_config['display_name'])

            if all_manual_bookings:
                log.debug(f"Found {len(all_manual_bookings)} previous {course_config['display_name']} bookings.")
            else:
                log.error(f"No previous {course_config['display_name']} bookings found. Cannot compare slots.")

            await tab.wait_for("#ctl00_HeaderSub_lblStoreValue", timeout=10)

            js_extract = """
            (() => {
                const el = document.getElementById('ctl00_HeaderSub_lblStoreValue');
                return el ? el.innerText.trim() : null;
            })();
            """
            value_str = await tab.evaluate(js_extract)

            if value_check and value_str:
                if isinstance(value_str, str):
                    clean_val = value_str.replace('$', '').strip()
                else:
                    log.error(f"Unexpected value type for store value: {type(value_str)}")
                    return
                
                try:
                    current_val = float(clean_val)
                    if current_val < 81.75:
                        msg = f"Store value is too low (${current_val}). Min required: $81.75. Bot stopped."
                        log.critical(msg)
                        bot.send(f"[!] {msg}", False)
                        return
                    else:
                        send_start_message(config, current_val, bot, all_manual_bookings)
                except ValueError:
                    log.error(f"Could not parse store value: '{value_str}'")

            await open_practical_safe(parser, tab, bot)

            # await parser.select_course()

            last_full_reload = time.time()
            last_stats_log = time.time()
            cycle_counter = 0
            ajax_failures = 0
            slot_found_counter = 0

            FULL_RELOAD_INTERVAL = 600
            MAX_AJAX_FAILURES = 5


            while True:
                cycle_start_time = time.perf_counter()
                current_time = time.time()

                # check_commands is sync, blocking but acceptable for now
                cmd = bot.check_commands()
                if cmd == "stop":
                    await parser.open_logout()
                    log.info("Stopping bot after receiving /stop.")
                    bot.send("Bot stopped via /stop command.", False)
                    break

                elif cmd == "status":
                    log.debug("Status command received.")
                    bot.send(f"✅ Bot is running. Last check: {datetime.now().strftime('%d/%b/%Y %H:%M:%S')}", False)

                elif cmd == "screen":
                    await anonymize_fields(tab)
                    await tab.save_screenshot("logs/tele_screenshot.png")
                    bot.send_photo("logs/tele_screenshot.png", "📸 Current screen of the bot. Fields anonymized.", False)
                
                elif cmd == "stats":
                    msg = (
                        f"📊 Bot Statistics:\n"
                        f"  - Slots found: {slot_found_counter}\n"
                        f"  - Cycles run: {cycle_counter}\n"
                    )
                    bot.send(msg, False)

                # success = await parser.trigger_postback_refresh()

                # if not success:
                #     log.info("Postback refresh failed. Performing hard reload...")
                #     await tab.reload()
                #     await cloudflare_handler(tab, bot)
                #     await parser.select_course()

                await tab.reload()
                await cloudflare_handler(tab, bot)
                await parser.select_course()


                all_slots =  await parser.get_slot_statuses()

                if all_slots:
                    slot_found_counter += 1
        
                    filtered = filter_practical_slots(all_slots, config, all_manual_bookings, bot)

                    current_mode = refresh_mode.on_slot_detected(all_slots, filtered)

                    if current_mode == "aggressive":
                        log.info(f"Aggressive mode enabled. Cycles remaining: {refresh_mode.aggressive_cycles}")
                    elif current_mode == "probe":
                        log.info(f"Probe mode enabled. Duration: {refresh_mode.probe_duration} seconds")
                    elif all_slots and current_mode == "none":
                        log.debug("Normal mode active, no aggressive or probe cycles remaining.")

                    if not filtered:
                        log.info("No matching slots found.")
                        cycle_end_time = time.perf_counter()
                        elapsed = cycle_end_time - cycle_start_time
                        log.info(f"Cycle {cycle_counter} completed in {elapsed * 1000:.2f}ms.")
                        await sleep_random(refresh_mode, backoff_multiplier)
                        cycle_counter += 1
                        continue
                else:
                    cycle_end_time = time.perf_counter()
                    elapsed = cycle_end_time - cycle_start_time
                    log.info(f"Cycle {cycle_counter} completed in {elapsed * 1000:.2f}ms.")
                    await sleep_random(refresh_mode, backoff_multiplier)
                    cycle_counter += 1
                    continue
                
                log.info(f"Found {len(filtered)} matching slots after filtering.")
                booked = False

                if dry_run:
                    for slot in filtered:
                        msg = f"Dry run enabled. Would book {slot['date']} session {slot['session']} ({slot['dayname']})"
                        log.info(msg)
                        bot.send(msg)
                    booked = True
                    break

                else:
                    booked_slots = []
                    for slot in filtered:
                        msg = f"[🔍] Trying to book: {slot['date']}, Session {slot['session']}, Day: {slot['dayname']}"
                        log.info(msg)
                        bot.send(msg, False)
                        result, addtionaltxt = await parser.reserve_slot(slot["element_id"])

                        if result == "success":
                            msg = f"[✔] Reserved: {slot['date']}, Session {slot['session']}, Day: {slot['dayname']}"
                            log.info(msg)
                            bot.send(msg, False)
                            
                            if auto_book:
                                if not await parser.confirm_booking():
                                    log.error("Auto-confirm booking failed. Please confirm manually.")
                                    bot.send("Auto-confirm booking failed. Please confirm manually.", False)
                                else:
                                    log.info("Auto-confirm enabled, booking has been confirmed.")
                                    bot.send("Auto-confirm enabled, booking has been confirmed.", False)

                            booked_slots.append(slot)

                        elif result == "no_change":
                            break

                        elif result == "alert":
                            bot.send(f"Alert detected: {addtionaltxt}. Please check manually. This slot will be skipped until resolved.", False)
                            continue

                        else:
                            pass

                    if booked_slots and not (dry_run or auto_book):
                        log.info(f"Waiting 3 minutes for user to confirm {len(booked_slots)} bookings...")
                        bot.send(f"You have booked {len(booked_slots)} slots. Please confirm them within 3 minutes.", False)
                        await asyncio.sleep(180)

                        log.info("Checking if booked sessions are now confirmed...")
                        
                        for slot in booked_slots:
                            confirmed = await is_slot_confirmed(tab, slot["date"], slot["session"], course_config['name'])
                            if confirmed:
                                msg = f"[✔] Booking confirmed: {slot['date']}, Session {slot['session']}, Day: {slot['dayname']}"
                                log.info(msg)
                                bot.send(msg, False)
                                booked = True
                                updated = await get_all_manual_bookings(tab, course_config['name'], course_config['display_name'])
                                
                                if updated:
                                    all_manual_bookings = updated
                                    log.debug(f"Updated {course_config['display_name']} bookings: {len(updated)} found.")
                                    
                                else:
                                    log.error(f"Failed to update new {course_config['display_name']} bookings.")
                            else:
                                msg = f"[X] Not confirmed: {slot['date']}, Session {slot['session']}, Day: {slot['dayname']} — please confirm manually and restart bot for updated bookings."
                                log.info(msg)
                                bot.send(msg, False)

                        await open_practical_safe(parser, tab, bot)
                if not booked:
                    log.warning("No slots booked this round. See logs for details.")
                    cycle_end_time = time.perf_counter()
                    elapsed = cycle_end_time - cycle_start_time
                    log.info(f"Cycle {cycle_counter} completed in {elapsed * 1000:.2f}ms.")
                    await sleep_random(refresh_mode, backoff_multiplier)
                    cycle_counter += 1
        else:
            log.critical("Login failed. Please check your credentials or restart the bot to try again.")
    except Exception as e:
        log.error(f"An error occurred: {e}")
        try:
            log.info("Attempting to capture error screenshot...")
            try:
                await anonymize_fields(tab)
            except Exception as anon_e:
                log.warning(f"Failed to anonymize fields before screenshot: {anon_e}")

            screenshot_path = "logs/error_screenshot.png"
            await tab.save_screenshot(screenshot_path)
            log.info(f"Screenshot saved to {screenshot_path}")
            
            caption = f"Application crashed: {str(e)}"
            if not bot.send_photo(screenshot_path, caption, notifyOff=False):
                bot.send(caption, False)
                
        except Exception as screenshot_e:
            log.error(f"Failed to capture/send error screenshot: {screenshot_e}")
            bot.send(f"Error occurred: {str(e)}\n(Screenshot failed: {screenshot_e})", False)
    finally:
        log.info("Closing tab and cleaning up resources.")
        browser.stop()

if __name__ == "__main__":
    # Windows specific event loop policy if needed, but usually default is fine for modern python
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())