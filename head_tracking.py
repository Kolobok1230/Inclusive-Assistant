import cv2
import mediapipe as mp
import pyautogui
import numpy as np
import threading
import time
import ctypes
from collections import deque

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False


def adjust_lighting(frame, clip_limit=2.0, tile_grid_size=(8, 8), gamma=1.2):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    l_eq = clahe.apply(l)
    if gamma != 1.0:
        look_up = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)]).astype("uint8")
        l_eq = cv2.LUT(l_eq, look_up)
    lab_eq = cv2.merge((l_eq, a, b))
    return cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)


class HeadTracker:
    def __init__(self, camera_source=0, **kwargs):
        self.camera_source = camera_source
        self.invert_x = kwargs.get('invert_x', True)
        self.swap_eyes = kwargs.get('swap_eyes', True)
        self.sensitivity_x = kwargs.get('sensitivity_x', 10.0) / 7.0
        self.sensitivity_y = kwargs.get('sensitivity_y', 12.0) / 7.0

        self.precision_interval_ms = kwargs.get('precision_interval_ms', 150)
        self.last_micro_move_time = 0

        self.reset_blinks_needed = 2
        self.reset_time_window = 1.5
        self.reset_candidates = []

        self.cursor_x, self.cursor_y = pyautogui.position()
        self.base_nose_x, self.base_nose_y = None, None
        self.running = False
        self.cap = None

        self.blink_limit = 0.22
        self.blink_open_hysteresis = 0.06
        self.long_press_ms = 500
        self.short_press_ms = 400
        self.dead_zone = 0.008
        self.precision_zone = 0.025

        self.left_eye_closed_start = 0
        self.left_button_held = False

        self.right_eye_closed_start = 0
        self.right_button_held = False
        self.right_blink_timestamps = deque(maxlen=5)

        self.ear_history = []
        self.ear_threshold_factor = 0.55
        self.min_blink_limit = 0.18
        self.max_blink_limit = 0.28

        self.was_left_open = True
        self.was_right_open = True
        self.was_both_open = True

        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(refine_landmarks=True)

        self.frame_counter = 0
        self.last_log_time = 0

    def update_settings(self, settings):
        self.sensitivity_x = settings.get('sx', 10) / 7.0
        self.sensitivity_y = settings.get('sy', 12) / 7.0
        self.invert_x = settings.get('inv_x', self.invert_x)
        self.swap_eyes = settings.get('swap', self.swap_eyes)
        self.precision_interval_ms = settings.get('ms', self.precision_interval_ms)
        self.camera_source = settings.get('cam', self.camera_source)

    def _get_ear(self, lm, eye_type='left'):
        if (eye_type == 'left' and not self.swap_eyes) or (eye_type == 'right' and self.swap_eyes):
            p1, p2, p3, p4 = lm[33], lm[133], lm[159], lm[145]
            brow = lm[70]
        else:
            p1, p2, p3, p4 = lm[362], lm[263], lm[386], lm[374]
            brow = lm[300]

        w = ((p1.x - p2.x)**2 + (p1.y - p2.y)**2)**0.5
        h = ((p3.x - p4.x)**2 + (p3.y - p4.y)**2)**0.5
        ear = h / (w + 1e-6)

        brow_dist_y = abs(p3.y - brow.y)

        is_held = self.left_button_held if eye_type == 'left' else self.right_button_held
        current_limit = (self.blink_limit + self.blink_open_hysteresis) if is_held else self.blink_limit

        if ear < current_limit and brow_dist_y > 0.055:
            return 0.35

        return ear

    def _update_blink_threshold(self, ear_l, ear_r):
        if ear_l > 0.2 and ear_r > 0.2:
            self.ear_history.append((ear_l, ear_r))
            if len(self.ear_history) > 60:
                self.ear_history.pop(0)
            if len(self.ear_history) > 10:
                avg_ear = np.mean([e for e, _ in self.ear_history] + [e for _, e in self.ear_history])
                new_limit = avg_ear * self.ear_threshold_factor
                self.blink_limit = max(self.min_blink_limit, min(self.max_blink_limit, new_limit))

    def _handle_left_eye(self, ear_left, now_ms):
        current_limit = (self.blink_limit + self.blink_open_hysteresis) if self.left_button_held else self.blink_limit

        if ear_left < current_limit:
            if self.left_eye_closed_start == 0:
                self.left_eye_closed_start = now_ms
            if (now_ms - self.left_eye_closed_start) > self.long_press_ms and not self.left_button_held:
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                self.left_button_held = True
        else:
            if self.left_eye_closed_start > 0:
                duration = now_ms - self.left_eye_closed_start
                if duration < self.short_press_ms and not self.left_button_held:
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                if self.left_button_held:
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                    self.left_button_held = False
                self.left_eye_closed_start = 0

    def _handle_right_eye(self, ear_right, now_ms):
        current_limit = (self.blink_limit + self.blink_open_hysteresis) if self.right_button_held else self.blink_limit

        if ear_right < current_limit:
            if self.right_eye_closed_start == 0:
                self.right_eye_closed_start = now_ms
            if (now_ms - self.right_eye_closed_start) > self.long_press_ms and not self.right_button_held:
                ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
                self.right_button_held = True
        else:
            if self.right_eye_closed_start > 0:
                duration = now_ms - self.right_eye_closed_start
                if duration < self.short_press_ms and not self.right_button_held:
                    self.right_blink_timestamps.append(now_ms)
                    while self.right_blink_timestamps and self.right_blink_timestamps[0] < now_ms - 1000:
                        self.right_blink_timestamps.popleft()
                    if len(self.right_blink_timestamps) >= 2:
                        ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
                        ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
                        ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
                        ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
                        self.right_blink_timestamps.clear()
                    else:
                        ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
                        ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
                if self.right_button_held:
                    ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
                    self.right_button_held = False
                self.right_eye_closed_start = 0

    def _track_loop(self):
        self.cap = cv2.VideoCapture(self.camera_source)
        if not self.cap.isOpened():
            self.running = False
            return

        screen_w, screen_h = pyautogui.size()
        both_blink_active = False

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                continue

            frame = adjust_lighting(frame)
            now_ts = time.time()
            now_ms = now_ts * 1000

            rgb = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
            results = self.face_mesh.process(rgb)

            if results.multi_face_landmarks:
                lm = results.multi_face_landmarks[0].landmark

                nose = lm[1]
                if self.base_nose_x is None:
                    self.base_nose_x, self.base_nose_y = nose.x, nose.y

                dx, dy = (nose.x - self.base_nose_x), (nose.y - self.base_nose_y)
                if self.invert_x:
                    dx = -dx
                dist = (dx**2 + dy**2)**0.5

                ear_l = self._get_ear(lm, 'left')
                ear_r = self._get_ear(lm, 'right')

                self._update_blink_threshold(ear_l, ear_r)

                if ear_l < self.blink_limit and ear_r < self.blink_limit and not self.left_button_held and not self.right_button_held:
                    self.left_eye_closed_start = 0
                    self.right_eye_closed_start = 0

                    if not both_blink_active:
                        self.reset_candidates.append(now_ts)
                        self.reset_candidates = [t for t in self.reset_candidates if now_ts - t <= self.reset_time_window]

                        if len(self.reset_candidates) >= self.reset_blinks_needed:
                            self.base_nose_x, self.base_nose_y = nose.x, nose.y
                            self.reset_candidates = []
                        both_blink_active = True
                else:
                    if ear_l >= (self.blink_limit + self.blink_open_hysteresis) and ear_r >= (self.blink_limit + self.blink_open_hysteresis):
                        both_blink_active = False

                    if not both_blink_active:
                        dist_moving_fast = (dist > 0.045)

                        if not (dist_moving_fast and not self.left_button_held):
                            self._handle_left_eye(ear_l, now_ms)
                        else:
                            self.left_eye_closed_start = 0

                        if not (dist_moving_fast and not self.right_button_held):
                            self._handle_right_eye(ear_r, now_ms)
                        else:
                            self.right_eye_closed_start = 0
                    else:
                        self.left_eye_closed_start = 0
                        self.right_eye_closed_start = 0

                if self.dead_zone < dist <= self.precision_zone:
                    if now_ms - self.last_micro_move_time > self.precision_interval_ms:
                        step = 2
                        if abs(dx) > abs(dy):
                            self.cursor_x += step if dx > 0 else -step
                        else:
                            self.cursor_y += step if dy > 0 else -step
                        self.last_micro_move_time = now_ms
                        pyautogui.moveTo(int(self.cursor_x), int(self.cursor_y))

                elif dist > self.precision_zone:
                    self.cursor_x += dx * self.sensitivity_x * 45
                    self.cursor_y += dy * self.sensitivity_y * 45
                    self.cursor_x = max(0, min(screen_w - 1, self.cursor_x))
                    self.cursor_y = max(0, min(screen_h - 1, self.cursor_y))
                    pyautogui.moveTo(int(self.cursor_x), int(self.cursor_y))

                else:
                    curr = pyautogui.position()
                    self.cursor_x, self.cursor_y = curr.x, curr.y

        self.cap.release()

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._track_loop, daemon=True).start()

    def stop(self):
        self.running = False