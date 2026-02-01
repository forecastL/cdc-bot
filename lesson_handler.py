import asyncio
import time
import json
from utils import logger
from utils.common import cloudflare_handler
from utils.logger import setup_logger

log = setup_logger(__name__)

class LessonHandler:
    def __init__(self, tab, course_value, course_display_name, course2_value, bot):
        self.tab = tab
        self.course_value = course_value
        self.course2_value = course2_value
        self.course_display_name = course_display_name
        self.bot = bot
        self.last_viewstate = None

    async def open_practical_booking_page(self):
        log.debug("Opening practical booking page...")
        # Navigate using the tab object directly
        await self.tab.get("https://bookingportal.cdc.com.sg/NewPortal/Booking/BookingPL.aspx")
        # await self.tab.get("https://bookingportal.cdc.com.sg/NewPortal/Booking/BookingPT.aspx")
        # await self.tab.get("https://bookingportal.cdc.com.sg/NewPortal/Booking/BookingETrial.aspx")

    async def open_logout(self):
        log.debug("Opening logout page...")
        await self.tab.get("https://bookingportal.cdc.com.sg/NewPortal/logOut.aspx?PageName=Logout")

    async def select_course(self):
        """
        Selects the course from the dropdown, retrying if the element is not found.
        Optimized for speed with robust error handling to prevent 'Could not find node' errors.
        """
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    log.debug(f"Attempt {attempt}/{max_retries} to select course...")
                
                try:
                    # Strategy: Check if element exists BEFORE trying to query it
                    # This prevents the "Could not find node" error
                    
                    # Step 1: Wait for element to exist in DOM
                    exists_check = """
                    (() => {
                        const el = document.getElementById('ctl00_ContentPlaceHolder1_ddlCourse');
                        return el !== null;
                    })();
                    """
                    
                    # Poll for element existence (faster than wait_for on reload)
                    element_found = False
                    for i in range(20):  # 20 * 0.25s = 5 second max wait
                        try:
                            exists = await self.tab.evaluate(exists_check)
                            if exists:
                                element_found = True
                                break
                        except Exception:
                            pass  # Element doesn't exist yet, keep trying
                        await asyncio.sleep(0.25)
                    
                    if not element_found:
                        raise Exception("Dropdown element not found in DOM after 5s")
                    
                    # Step 2: Verify it's visible and interactive
                    visibility_check = """
                    (() => {
                        const el = document.getElementById('ctl00_ContentPlaceHolder1_ddlCourse');
                        if (!el) return false;
                        if (el.offsetParent === null) return false;  // Hidden
                        if (el.disabled) return false;  // Disabled
                        return true;
                    })();
                    """
                    
                    is_ready = await self.tab.evaluate(visibility_check)
                    if not is_ready:
                        raise Exception("Dropdown exists but is not visible/interactive")
                    
                    # Small buffer to ensure it's fully interactive
                    await asyncio.sleep(0.2)
                        
                except Exception as e:
                    log.warning(f"Attempt {attempt}/{max_retries}: Course dropdown issue: {e}")
                    if attempt < max_retries:
                        log.info(f"Refreshing page and retrying...")
                        await self.tab.reload()
                        
                        # Wait for page to settle after reload
                        await asyncio.sleep(2.0)
                        
                        # Check for Cloudflare
                        await cloudflare_handler(self.tab, self.bot)
                        
                        # Additional buffer after CF check
                        await asyncio.sleep(0.5)
                        
                        continue 
                    else:
                        raise Exception(f"Failed to select course: {e}")
                
                # Step 3: Select the course (element is guaranteed to exist now)
                js_script = f"""
                (() => {{
                    const select = document.getElementById('ctl00_ContentPlaceHolder1_ddlCourse');
                    if (!select) return false;
                    
                    // Verify value exists in options
                    const optionExists = Array.from(select.options).some(opt => opt.value === '{self.course_value}');
                    if (!optionExists) {{
                        console.error('Course value not found in dropdown options');
                        return false;
                    }}
                    
                    select.value = '{self.course_value}';
                    
                    // Trigger change event
                    const event = new Event('change', {{ bubbles: true }});
                    select.dispatchEvent(event);
                    
                    return true;
                }})();
                """

                success = await self.tab.evaluate(js_script)
                
                if success:
                    if attempt == 1:
                        log.debug(f"Selected {self.course_display_name} course.")
                    else:
                        log.info(f"Selected {self.course_display_name} course on attempt {attempt}.")
                    return
                else:
                    raise Exception("JS Selection script returned false")
            
            except Exception as e:
                if attempt == max_retries:
                    try:
                        await self.tab.save_screenshot("logs/error_select_course.png")
                    except: 
                        pass
                    log.error(f"Failed to select course: {e}")
                    raise Exception(f"Failed to select course: {e}")
                else:
                    # Brief pause before retry
                    await asyncio.sleep(0.5)

    async def wait_for_full_booking_msg_or_table(self, timeout=6.5, poll_interval=0.05):
        """
        Waits for either:
        - Full booking message (return True)
        - Slot table (return False)
        
        Ignores progress spinner - just waits for final result.
        """
        t_start = time.perf_counter()
        end_time = t_start + timeout
        
        check_script = """
        (() => {
            // Check for full booking message (priority 1)
            var msg = document.getElementById('ctl00_ContentPlaceHolder1_lblFullBookMsg');
            if (msg && msg.style.display !== 'none' && msg.offsetParent !== null) {
                return 'full_msg';
            }
            
            // Check for slot table (priority 2)
            var table = document.getElementById('ctl00_ContentPlaceHolder1_gvLatestav');
            if (table && table.style.display !== 'none' && table.offsetParent !== null) {
                return 'table';
            }
            
            // Still waiting (spinner may or may not be visible)
            return 'waiting';
        })();
        """

        while time.perf_counter() < end_time:
            try:
                status = await self.tab.evaluate(check_script)
                
                if status == 'full_msg':
                    elapsed = (time.perf_counter() - t_start) * 1000
                    log.debug(f"Full booking message displayed. {elapsed:.2f}ms")
                    return True
                
                elif status == 'table':
                    elapsed = (time.perf_counter() - t_start) * 1000
                    log.debug(f"Slot table displayed. {elapsed:.2f}ms")
                    return False
                
                # Still waiting - continue polling (ignore spinner state)
                
            except Exception as e:
                log.debug(f"Poll error: {e}")
                pass

            await asyncio.sleep(poll_interval)

        # Timeout reached - server didn't respond in 25 seconds
        elapsed = (time.perf_counter() - t_start) * 1000
        log.error(f"⚠️ Timeout after {elapsed:.0f}ms - server not responding!")
        
        # Take screenshot for debugging
        try:
            await self.tab.save_screenshot("logs/timeout_spinner.png")
        except:
            pass
        
        # Reload and retry
        log.warning("Reloading page after timeout...")
        await self.tab.reload()
        await asyncio.sleep(1.5)
        await cloudflare_handler(self.tab, self.bot)
        await asyncio.sleep(0.5)
        await self.select_course()
        
        # Try one more time after reload
        return await self.wait_for_full_booking_msg_or_table(timeout=15, poll_interval=0.05)

    async def get_slot_statuses(self):
        """
        Returns a list of slot dictionaries using robust JSON extraction.
        """
        log.debug(f"Getting slot statuses...")
        slot_data = []

        status_map = {
            "images0.gif": "unavailable",
            "images1.gif": "available",
            "images2.gif": "reserved",
            "images3.gif": "booked"
        }

        if await self.wait_for_full_booking_msg_or_table():
            return []
        
        t_pass_full_msg = time.perf_counter()

        try:
            # FIX: Use JSON.stringify to ensure we get pure data back
            js_extract = """
            (() => {
                var rows = Array.from(document.querySelectorAll('#ctl00_ContentPlaceHolder1_gvLatestav tr')).slice(1);
                var results = [];
                rows.forEach(row => {
                    var tds = row.querySelectorAll('td');
                    if (tds.length < 2) return;
                    
                    var date = tds[0].innerText.trim();
                    var dayname = tds[1].innerText.trim();
                    var inputs = row.querySelectorAll('input[src]');
                    
                    inputs.forEach((input, index) => {
                        var src = input.getAttribute('src');
                        if (src) {
                            var img_src = src.split('/').pop().toLowerCase();
                            results.push({
                                date: date,
                                dayname: dayname,
                                session: index + 1,
                                img_src: img_src,
                                element_id: input.id
                            });
                        }
                    });
                });
                return JSON.stringify(results);
            })();
            """
            
            # 1. Get string
            json_str = await self.tab.evaluate(js_extract)
            # 2. Parse string
            raw_slots = json.loads(json_str)
            
            for slot in raw_slots:
                status = status_map.get(slot['img_src'], "unknown")
                # log.debug(f"Slot: {slot['date']} S{slot['session']} = {status}")

                if status == "available":
                    slot_data.append({
                        "date": slot['date'],
                        "dayname": slot['dayname'],
                        "session": slot['session'],
                        "status": status,
                        "element_id": slot['element_id']
                    })

        except Exception as e:
            try:
                await self.tab.save_screenshot("logs/error_slots.png")
            except: pass
            log.error(f"Error parsing slots: {e}")

        log.info(f"Found {len(slot_data)} available slots.")
        return slot_data
        
    async def reserve_slot(self, element_id):
        try:
            t_start = time.perf_counter()
            
            # Select element
            input_elem = await self.tab.select(f"#{element_id}")
            
            # Override alert to capture text (Prevent blocking)
            await self.tab.evaluate("window.lastAlert = null; window.alert = function(msg) { window.lastAlert = msg; return true; }")
            
            await input_elem.click()
            log.debug(f"Clicked booking button: {element_id}")

            # Check for alert
            await asyncio.sleep(0.5)
            alert_text = await self.tab.evaluate("window.lastAlert")
            if alert_text:
                log.warning(f"Alert detected: {alert_text}")
                return "alert", alert_text

            # Wait for spinner to disappear
            try:
                for _ in range(20):
                    visible = await self.tab.evaluate("document.getElementById('ctl00_ContentPlaceHolder1_UpdateProgress1').style.display !== 'none'")
                    if not visible: break
                    await asyncio.sleep(0.5)
            except: pass
        
            # Wait for image change
            new_src = None
            try:
                for _ in range(5): 
                    new_src = await self.tab.evaluate(f"document.getElementById('{element_id}').getAttribute('src')")
                    if new_src and "Images2.gif" in new_src:
                        break
                    await asyncio.sleep(0.5)
            except: pass

            if new_src and "Images2.gif" in new_src:
                log.info(f"Successfully booked: {element_id}")
                return "success", ""
            else:
                log.info(f"Unsuccessful booking. Src remains: {new_src}")
                return "no_change", ""

        except Exception as e:
            log.error(f"Error clicking element {element_id}: {e}")
            return "error", ""
            
    async def confirm_booking(self):
        try:
            # 1. Click CHECKOUT
            checkout_btn = await self.tab.wait_for("#ctl00_ContentPlaceHolder1_btnCheckout", timeout=10)
            
            # Alert override
            await self.tab.evaluate("window.lastAlert = null; window.alert = function(msg) { window.lastAlert = msg; return true; }")
            
            await checkout_btn.click()
            log.info("Clicked checkout.")
            
            await asyncio.sleep(1) # Wait for page load
            
            # 2. Click CONFIRM
            # Need to wait for next page or button appearance
            try:
                confirm_btn = await self.tab.wait_for("#ctl00_ContentPlaceHolder1_btnConfirm", timeout=10)
            except:
                log.error("Confirm button did not appear.")
                return False

            await self.tab.evaluate("window.lastAlert = null; window.alert = function(msg) { window.lastAlert = msg; return true; }")
            
            await confirm_btn.click()
            log.info("Clicked confirm.")
            
            await asyncio.sleep(2) # Wait for final processing

            # Check final URL
            current_url = await self.tab.evaluate("window.location.href")
            if "ReportPrView.aspx" in current_url:
                log.info("Booking confirmed successfully!")
                return True
            else:
                log.error(f"Confirmation failed. URL: {current_url}")
                return False

        except Exception as e:
            log.error(f"Error during confirmation: {e}")
            return False
        
    async def trigger_postback_refresh(self):
        """
        Triggers the update and waits for the ASP.NET 'endRequest' event.
        Uses an IIFE (Immediately Invoked Function Expression) to ensure execution.
        """
        try:
            log.debug("Triggering ASP.NET Postback via JS Hook...")

            # KEY CHANGE: The script is now wrapped in (() => { ... })();
            js_script = """
            (() => {
                return new Promise((resolve) => {
                    try {
                        // 1. Safety Check: Ensure ASP.NET AJAX is loaded
                        if (typeof Sys === 'undefined' || typeof Sys.WebForms === 'undefined') {
                            resolve('error: ASP.NET Sys object not found');
                            return;
                        }

                        var prm = Sys.WebForms.PageRequestManager.getInstance();
                        
                        // 2. Define the listener
                        var onEndRequest = function(sender, args) {
                            prm.remove_endRequest(onEndRequest); // Clean up
                            
                            // Check if there was a server error
                            if (args.get_error()) {
                                args.set_errorHandled(true);
                                resolve('error: Server-side exception');
                            } else {
                                resolve('success');
                            }
                        };

                        // 3. Attach listener
                        prm.add_endRequest(onEndRequest);

                        // 4. Trigger Postback
                        __doPostBack('ctl00$ContentPlaceHolder1$ddlCourse','');

                        // 5. Safety Timeout (5 seconds)
                        setTimeout(() => {
                            prm.remove_endRequest(onEndRequest);
                            resolve('timeout');
                        }, 5000);
                        
                    } catch (e) {
                        resolve('error: ' + e.message);
                    }
                });
            })();
            """

            # Execute and wait for the Promise to resolve
            result = await self.tab.evaluate(js_script, await_promise=True)

            if result == 'success':
                # --- NEW VERIFICATION LOGIC ---
                try:
                    # Extract the hidden ViewState token
                    current_viewstate = await self.tab.evaluate("document.getElementById('__VIEWSTATE').value")
                    
                    # Compare it with the previous one
                    if self.last_viewstate:
                        if current_viewstate != self.last_viewstate:
                            log.debug("✅ Pulse Check: Server State CHANGED (Fresh Data).")
                        else:
                            log.warning("⚠️ Pulse Check: Server State IDENTICAL (Possible Stagnation).")
                    
                    # Update the memory
                    self.last_viewstate = current_viewstate
                    
                except Exception as e:
                    log.debug(f"Could not verify ViewState: {e}")
                # -----------------------------

                await asyncio.sleep(0.2)
                return True
                
            elif result == 'timeout':
                log.warning("Postback timed out (endRequest never fired).")
                return False
                
            else:
                log.error(f"Postback script error: {result}")
                return False

        except Exception as e:
            log.error(f"Postback critical failure: {e}")
            return False