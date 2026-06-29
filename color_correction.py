import winreg
import ctypes
import time

class ColorCorrectionOverlay:
    FILTER_TYPES = {
        "protanomaly": 3,
        "deuteranomaly": 4,
        "tritanomaly": 5
    }

    def __init__(self, correction_type="deuteranomaly", intensity=0.7, gain=0.7):
        self.correction_type = correction_type
        self.intensity = intensity
        self.gain = gain
        self.active = False

    def _send_hotkey(self):
        user32 = ctypes.windll.user32
        user32.keybd_event(0x5B, 0, 0, 0)  # Win
        user32.keybd_event(0xA2, 0, 0, 0)  # Ctrl
        user32.keybd_event(0x43, 0, 0, 0)  # C
        time.sleep(0.05)
        user32.keybd_event(0x43, 0, 2, 0)
        user32.keybd_event(0xA2, 0, 2, 0)
        user32.keybd_event(0x5B, 0, 2, 0)

    def _apply_filter(self, enable, filter_type=None, intensity=None, gain=None):
        key_path = r"Software\Microsoft\ColorFiltering"
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "Active", 0, winreg.REG_DWORD, 1 if enable else 0)
                if enable and filter_type is not None:
                    winreg.SetValueEx(key, "FilterType", 0, winreg.REG_DWORD, filter_type)
                if intensity is not None:
                    winreg.SetValueEx(key, "Intensity", 0, winreg.REG_DWORD, int(intensity * 100))
                if gain is not None:
                    winreg.SetValueEx(key, "Gain", 0, winreg.REG_DWORD, int(gain * 100))
                winreg.SetValueEx(key, "HotkeyEnabled", 0, winreg.REG_DWORD, 1)
            time.sleep(0.1)
            self._send_hotkey()
            return True
        except Exception as e:
            return False

    def stop(self):
        filter_val = self.FILTER_TYPES.get(self.correction_type)
        if filter_val is None:
            return
        self._apply_filter(True, filter_val, self.intensity, self.gain)
        self.active = True

    def start(self):
        if not self.active:
            return
        self._apply_filter(False)
        self.active = False

    def set_correction_type(self, corr_type):
        if corr_type in self.FILTER_TYPES:
            self.correction_type = corr_type
            if self.active:
                self._apply_filter(True, self.FILTER_TYPES[corr_type], self.intensity, self.gain)


    def set_intensity(self, intensity):
        self.intensity = max(0.0, min(1.0, intensity))
        if self.active:
            self._apply_filter(True, self.FILTER_TYPES.get(self.correction_type), self.intensity, self.gain)


    def set_gain(self, gain):
        self.gain = max(0.0, min(1.0, gain))
        if self.active:
            self._apply_filter(True, self.FILTER_TYPES.get(self.correction_type), self.intensity, self.gain)
