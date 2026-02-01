import asyncio
from utils.common import wait_for_elem, cloudflare_handler
from utils.logger import setup_logger

log = setup_logger(__name__)

class LoginManager:
    def __init__(self, tab, username, password, bot):
        self.tab = tab
        self.username = username
        self.password = password
        self.bot = bot

    async def login(self):
        log.debug("Login started.")

        await cloudflare_handler(self.tab, self.bot)

        await self.tab.get("https://www.cdc.com.sg")

        await wait_for_elem(self.tab, "login")

        log.debug("Clicking login button.")
        login_btn = await self.tab.select("#login")
        await login_btn.click()

        await wait_for_elem(self.tab, "login-form")

        # Wait for the username field to be visible
        # nodriver wait_for returns the element when found
        await self.tab.wait_for(selector="[name='userId_4']", timeout=10)

        log.debug(f"Entering login details for {self.username}.")
        user_input = await self.tab.select("[name='userId_4']")
        await user_input.send_keys(self.username)
        
        pass_input = await self.tab.select("[name='password_4']")
        await pass_input.send_keys(self.password)

        log.warning("Please complete CAPTCHA manually.")
        # input() is blocking, but in this context we might need to use asyncio.to_thread or just block if acceptable.
        # Since this is a CLI tool, blocking input is fine for now, but strictly speaking it blocks the event loop.
        # However, we are just waiting for user.
        print("Press ENTER after login is complete...")
        await asyncio.to_thread(input)

        log.debug("Submitting login form.")
        submit_btn = await self.tab.select(".btn-login-submit")
        await submit_btn.click()

        try:
            # Wait for URL to contain bookingportal
            # nodriver doesn't have a direct "wait for url contains" but we can loop check
            for _ in range(20): # 10 seconds (0.5 * 20)
                # nodriver: evaluate location.href
                current_url = await self.tab.evaluate("window.location.href")
                if "bookingportal.cdc.com.sg" in current_url:
                    return True
                await asyncio.sleep(0.5)
            return False
        except Exception as e:
            return False