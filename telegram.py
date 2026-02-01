import requests
from utils.logger import setup_logger

log = setup_logger(__name__)

class TelegramBot:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._last_checked_update_id = None

        self.clear_updates()
        self.init_last_update_id()

    def send(self, message, notifyOff=True):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_notification": notifyOff,
            "protect_content": True
        }
        try:
            response = requests.post(url, data=data)
            return response.status_code == 200
        except Exception as e:
            print("[!] Telegram send failed:", e)
            return False
    
    def send_photo(self, photo_path, caption=None, notifyOff=True):
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        files = {'photo': open(photo_path, 'rb')}
        data = {
            "chat_id": self.chat_id,
            "caption": caption,
            "disable_notification": notifyOff,
            "protect_content": True
        }
        try:
            response = requests.post(url, files=files, data=data)
            return response.status_code == 200
        except Exception as e:
            print("[!] Telegram send photo failed:", e)
            return False
    
    def check_commands(self):
        try:
            offset = (self._last_checked_update_id + 1) if self._last_checked_update_id is not None else 0
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?offset={offset}"
            resp = requests.get(url).json()

            if "result" not in resp:
                return None

            for update in resp["result"]:
                update_id = update["update_id"]
                self._last_checked_update_id = update_id

                if str(update["message"]["chat"]["id"]) != self.chat_id:
                    continue

                text = update["message"]["text"].strip().lower()
                if text == "/stop":
                    return "stop"
                elif text == "/status":
                    return "status"
                elif text == "/screen":
                    return "screen"
                elif text == "/stats":
                    return "stats"
        
        except Exception as e:
            print(f"[!] Error checking Telegram commands: {e}")
        return None
    
    def init_last_update_id(self):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?limit=1"
            resp = requests.get(url).json()
            if "result" in resp and resp["result"]:
                self._last_checked_update_id = resp["result"][-1]["update_id"]
                log.debug(f"[i] Initialized last update ID to {self._last_checked_update_id}")
        except Exception as e:
            print(f"[!] Failed to initialize update ID: {e}")

    def clear_updates(self):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            resp = requests.get(url).json()

            if "result" in resp and resp["result"]:
                last_update_id = resp["result"][-1]["update_id"]
                clear_url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?offset={last_update_id + 1}"
                requests.get(clear_url)
                log.debug(f"[i] Cleared all pending updates up to {last_update_id}")
        except Exception as e:
            print(f"[!] Failed to clear Telegram updates: {e}")