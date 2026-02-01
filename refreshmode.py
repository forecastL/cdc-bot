import time
import random

class RefreshMode:
    def __init__(self, probe_duration=10, aggro_range=(6, 8)):
        self.probe_mode = False
        self.aggressive_cycles = 0
        self.probe_start = None
        self.probe_duration = probe_duration
        self.aggro_range = aggro_range

    def trigger_aggressive_mode(self):
        if self.aggressive_cycles < 4:
            self.aggressive_cycles = random.randint(*self.aggro_range)

    def on_slot_detected(self, slots_found, filtered_slots_found):
        if filtered_slots_found:
            self.trigger_aggressive_mode()
            self.probe_mode = False
            self.probe_start = None
            return "aggressive"

        if slots_found and not self.in_aggressive():
            if not self.probe_mode:
                self.probe_mode = True
                self.probe_start = time.time()
                return "probe"

        return "none"

    def tick(self):
        if self.aggressive_cycles > 0:
            self.aggressive_cycles -= 1

        # Fix probe mode timeout logic
        if self.probe_mode and self.probe_start is not None:
            elapsed_time = time.time() - self.probe_start
            if elapsed_time > self.probe_duration:
                self.probe_mode = False
                self.probe_start = None

    def in_probe(self):
        return self.probe_mode

    def in_aggressive(self):
        return self.aggressive_cycles > 0
