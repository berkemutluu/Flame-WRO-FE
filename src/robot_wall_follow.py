import json
import os
import threading
import time
import webbrowser
from copy import deepcopy

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template_string, request

try:
    import serial
except ImportError:
    serial = None

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None


# --- CONFIGURATION ---
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
FRAME_SIZE = (640, 480)
STREAM_FPS = 20
DEBUG = True
AUTO_OPEN_BROWSER = False

DEFAULT_COLORS = {
    "REDLO": [0, 100, 80],
    "REDHI": [10, 255, 255],
    "RED_HEX_LO": "#5a0000",
    "RED_HEX_HI": "#ff0000",
    "GREENLO": [40, 40, 30],
    "GREENHI": [85, 255, 255],
    "GREEN_HEX_LO": "#002800",
    "GREEN_HEX_HI": "#00ff00",
    "ORANGELO": [7, 20, 10],
    "ORANGEHI": [37, 255, 255],
    "ORANGE_HEX_LO": "#5a2800",
    "ORANGE_HEX_HI": "#ff8c00",
    "BLUELO": [100, 85, 90],
    "BLUEHI": [130, 255, 255],
    "BLUE_HEX_LO": "#00005a",
    "BLUE_HEX_HI": "#0000ff",
    "PINKLO": [158, 160, 100],
    "PINKHI": [170, 255, 255],
    "PINK_HEX_LO": "#5a0028",
    "PINK_HEX_HI": "#ff00ff",
}

DEFAULT_TRACKING = {
    "RED": False,
    "GREEN": True,
    "ORANGE": False,
    "BLUE": False,
    "PINK": False,
    "WALLS": True,
}

DEFAULT_CAMERA_SETTINGS = {
    "crop_height": 200,
    "gray_thresh": 110,
    "threshold_mode": "MANUAL",
    "follow_side": "AUTO",
    "debug_overlay": True,
    "drive_enabled": True,
    "flip_code": -1,
    "wall_target_portion": 0.45,
    "wall_kp": 100.0,
    "wall_kd": 8.0,
    "center_kp": 90.0,
    "base_speed": 210,
    "min_speed": 150,
    "max_speed": 230,
    "max_steer": 45,
    "steering_sign": 1,
    "side_band_portion": 0.28,
    "analysis_start_portion": 0.15,
    "auto_side_margin": 0.05,
    "lost_wall_min_portion": 0.018,
    "emergency_wall_portion": 0.72,
    "min_wall_area": 80,
    "lost_wall_stop": True,
    "jpeg_quality": 80,
}

DEFAULT_SERIAL_SETTINGS = {
    "port": "/dev/ttyUSB0",
    "baud_rate": 9600,
    "drive_sign": -1,
    "send_interval": 0.05,
    "max_speed_step": 14,
}


# --- SHARED STATE ---
output_frame = None
output_lock = threading.Lock()
config_lock = threading.Lock()
status_lock = threading.Lock()
stop_event = threading.Event()
app = Flask(__name__)

current_colors = deepcopy(DEFAULT_COLORS)
current_tracking = deepcopy(DEFAULT_TRACKING)
camera_settings = deepcopy(DEFAULT_CAMERA_SETTINGS)
serial_settings = deepcopy(DEFAULT_SERIAL_SETTINGS)
runtime_status = {
    "camera": "starting",
    "serial": "starting",
    "mode": "idle",
    "side": "LEFT",
    "left_portion": 0.0,
    "right_portion": 0.0,
    "steering": 0,
    "speed": 0,
    "fps": 0.0,
    "message": "",
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def to_int(value, default, lo=None, hi=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if lo is not None:
        number = max(lo, number)
    if hi is not None:
        number = min(hi, number)
    return number


def to_float(value, default, lo=None, hi=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if lo is not None:
        number = max(lo, number)
    if hi is not None:
        number = min(hi, number)
    return number


def to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if value is None:
        return default
    return bool(value)


def normalize_camera_settings(settings):
    normalized = deepcopy(DEFAULT_CAMERA_SETTINGS)
    normalized.update(settings or {})

    normalized["crop_height"] = to_int(normalized.get("crop_height"), 200, 0, FRAME_SIZE[1] - 2)
    normalized["gray_thresh"] = to_int(normalized.get("gray_thresh"), 110, 0, 255)
    normalized["threshold_mode"] = str(normalized.get("threshold_mode", "MANUAL")).upper()
    if normalized["threshold_mode"] not in ("MANUAL", "ADAPTIVE"):
        normalized["threshold_mode"] = "MANUAL"

    normalized["follow_side"] = str(normalized.get("follow_side", "AUTO")).upper()
    if normalized["follow_side"] not in ("AUTO", "LEFT", "RIGHT"):
        normalized["follow_side"] = "AUTO"

    normalized["debug_overlay"] = to_bool(normalized.get("debug_overlay"), True)
    normalized["drive_enabled"] = to_bool(normalized.get("drive_enabled"), True)
    flip_code = normalized.get("flip_code", -1)
    normalized["flip_code"] = None if flip_code in (None, "none", "NONE", "") else to_int(flip_code, -1, -1, 1)

    normalized["wall_target_portion"] = to_float(normalized.get("wall_target_portion"), 0.45, 0.05, 0.9)
    normalized["wall_kp"] = to_float(normalized.get("wall_kp"), 100.0, 0.0, 400.0)
    normalized["wall_kd"] = to_float(normalized.get("wall_kd"), 8.0, 0.0, 80.0)
    normalized["center_kp"] = to_float(normalized.get("center_kp"), 90.0, 0.0, 300.0)
    normalized["base_speed"] = to_int(normalized.get("base_speed"), 210, 0, 255)
    normalized["min_speed"] = to_int(normalized.get("min_speed"), 150, 0, 255)
    normalized["max_speed"] = to_int(normalized.get("max_speed"), 230, 0, 255)
    if normalized["min_speed"] > normalized["max_speed"]:
        normalized["min_speed"], normalized["max_speed"] = normalized["max_speed"], normalized["min_speed"]

    normalized["max_steer"] = to_int(normalized.get("max_steer"), 45, 0, 75)
    normalized["steering_sign"] = -1 if to_int(normalized.get("steering_sign"), 1) < 0 else 1
    normalized["side_band_portion"] = to_float(normalized.get("side_band_portion"), 0.28, 0.12, 0.45)
    normalized["analysis_start_portion"] = to_float(normalized.get("analysis_start_portion"), 0.15, 0.0, 0.6)
    normalized["auto_side_margin"] = to_float(normalized.get("auto_side_margin"), 0.05, 0.01, 0.25)
    normalized["lost_wall_min_portion"] = to_float(normalized.get("lost_wall_min_portion"), 0.018, 0.0, 0.2)
    normalized["emergency_wall_portion"] = to_float(normalized.get("emergency_wall_portion"), 0.72, 0.3, 1.0)
    normalized["min_wall_area"] = to_int(normalized.get("min_wall_area"), 80, 0, 20000)
    normalized["lost_wall_stop"] = to_bool(normalized.get("lost_wall_stop"), True)
    normalized["jpeg_quality"] = to_int(normalized.get("jpeg_quality"), 80, 30, 95)
    return normalized


def normalize_serial_settings(settings):
    normalized = deepcopy(DEFAULT_SERIAL_SETTINGS)
    normalized.update(settings or {})
    normalized["port"] = str(normalized.get("port") or DEFAULT_SERIAL_SETTINGS["port"])
    normalized["baud_rate"] = to_int(normalized.get("baud_rate"), 9600, 1200, 115200)
    normalized["drive_sign"] = -1 if to_int(normalized.get("drive_sign"), -1) < 0 else 1
    normalized["send_interval"] = to_float(normalized.get("send_interval"), 0.05, 0.02, 0.5)
    normalized["max_speed_step"] = to_int(normalized.get("max_speed_step"), 14, 1, 255)
    return normalized


def hex_to_hsv(hex_str):
    hex_str = (hex_str or "").lstrip("#")
    if len(hex_str) != 6:
        return [0, 0, 0]
    try:
        r, g, b = tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return [0, 0, 0]
    hsv_img = cv2.cvtColor(np.uint8([[[r, g, b]]]), cv2.COLOR_RGB2HSV)
    return [int(x) for x in hsv_img[0][0]]


def hsv_to_hex(h, s, v):
    rgb_img = cv2.cvtColor(np.uint8([[[int(h), int(s), int(v)]]]), cv2.COLOR_HSV2RGB)
    r, g, b = rgb_img[0][0]
    return f"#{r:02x}{g:02x}{b:02x}"


def load_config():
    global current_colors, current_tracking, camera_settings, serial_settings
    if not os.path.exists(CONFIG_PATH):
        return

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as exc:
        print(f"Error loading config: {exc}")
        return

    with config_lock:
        if isinstance(cfg.get("colors"), dict):
            current_colors.update(cfg["colors"])
        if isinstance(cfg.get("tracking"), dict):
            current_tracking.update(cfg["tracking"])
        if isinstance(cfg.get("camera"), dict):
            camera_settings.update(cfg["camera"])
        if isinstance(cfg.get("serial"), dict):
            serial_settings.update(cfg["serial"])

        if "GRAY" in current_colors and "gray_thresh" not in camera_settings:
            camera_settings["gray_thresh"] = current_colors["GRAY"]

        camera_settings = normalize_camera_settings(camera_settings)
        serial_settings = normalize_serial_settings(serial_settings)

        for color in ("RED", "GREEN", "ORANGE", "BLUE", "PINK"):
            lo_key = f"{color}LO"
            hi_key = f"{color}HI"
            if lo_key in current_colors and f"{color}_HEX_LO" not in current_colors:
                current_colors[f"{color}_HEX_LO"] = hsv_to_hex(*current_colors[lo_key])
            if hi_key in current_colors and f"{color}_HEX_HI" not in current_colors:
                current_colors[f"{color}_HEX_HI"] = hsv_to_hex(*current_colors[hi_key])


def save_all_to_disk():
    with config_lock:
        cfg = {
            "colors": current_colors,
            "tracking": current_tracking,
            "camera": camera_settings,
            "serial": serial_settings,
        }

    tmp_path = CONFIG_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception as exc:
        print(f"Failed to save config: {exc}")


def get_config_snapshot():
    with config_lock:
        return {
            "colors": deepcopy(current_colors),
            "tracking": deepcopy(current_tracking),
            "camera": deepcopy(camera_settings),
            "serial": deepcopy(serial_settings),
        }


def update_runtime_status(**values):
    with status_lock:
        runtime_status.update(values)


def get_runtime_status():
    with status_lock:
        return deepcopy(runtime_status)


def make_text_frame(lines, color=(255, 255, 255)):
    img = np.zeros((FRAME_SIZE[1], FRAME_SIZE[0], 3), dtype=np.uint8)
    if isinstance(lines, str):
        lines = [lines]
    y = 210
    for line in lines:
        cv2.putText(
            img,
            str(line),
            (24, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            color,
            2,
            cv2.LINE_AA,
        )
        y += 34
    ok, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes() if ok else None


class ArduinoController:
    def __init__(self, settings):
        self.ser = None
        self.settings = normalize_serial_settings(settings)
        self.last_steering = None
        self.last_drive = 0
        self.last_update = 0.0

        if serial is None:
            update_runtime_status(serial="pyserial missing")
            print("Arduino Warning: pyserial is not installed.")
            return

        try:
            self.ser = serial.Serial(
                port=self.settings["port"],
                baudrate=self.settings["baud_rate"],
                timeout=0.2,
                write_timeout=0.2,
            )
            time.sleep(2)
            self.ser.reset_input_buffer()
            update_runtime_status(serial=f"connected {self.settings['port']}")
        except Exception as exc:
            update_runtime_status(serial=f"not connected: {exc}")
            print(f"Arduino Warning: {exc}")
            self.ser = None

    def send_command(self, command):
        if not self.ser:
            return
        try:
            self.ser.write(f"{command}\n".encode("ascii"))
            self.ser.flush()
        except Exception as exc:
            update_runtime_status(serial=f"send error: {exc}")
            print(f"Arduino send error: {exc}")

    def update(self, steering, speed):
        now = time.monotonic()
        interval = self.settings["send_interval"]
        if now - self.last_update < interval:
            return

        steering = int(clamp(steering, -75, 75))
        requested_drive = int(clamp(speed, -255, 255))
        if requested_drive == 0:
            drive = 0
        else:
            max_step = self.settings["max_speed_step"]
            drive_delta = clamp(requested_drive - self.last_drive, -max_step, max_step)
            drive = int(self.last_drive + drive_delta)

        if steering != self.last_steering:
            self.send_command(f"STEER:{steering}")
            self.last_steering = steering

        if drive != self.last_drive or requested_drive == 0:
            self.send_command(f"DRIVE:{drive}")
            self.last_drive = drive

        self.last_update = now

    def stop(self):
        self.last_drive = 0
        self.send_command("STEER:0")
        self.send_command("DRIVE:0")

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()


class WallFollower:
    def __init__(self):
        self.last_error = 0.0
        self.last_time = None
        self.last_side = "LEFT"
        self.last_mode = "idle"
        self.smooth_left = 0.0
        self.smooth_right = 0.0

    def make_wall_mask(self, roi_bgr, settings):
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if settings["threshold_mode"] == "ADAPTIVE":
            wall_mask = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                21,
                5,
            )
        else:
            _, wall_mask = cv2.threshold(
                gray,
                int(settings["gray_thresh"]),
                255,
                cv2.THRESH_BINARY_INV,
            )

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        wall_mask = cv2.morphologyEx(wall_mask, cv2.MORPH_OPEN, kernel)
        wall_mask = cv2.morphologyEx(wall_mask, cv2.MORPH_CLOSE, kernel)

        min_area = int(settings["min_wall_area"])
        if min_area > 0:
            filtered = np.zeros_like(wall_mask)
            contours, _ = cv2.findContours(wall_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if cv2.contourArea(contour) >= min_area:
                    cv2.drawContours(filtered, [contour], -1, 255, thickness=cv2.FILLED)
            wall_mask = filtered

        return wall_mask

    def select_side(self, left_portion, right_portion, settings):
        requested = settings["follow_side"]
        if requested in ("LEFT", "RIGHT"):
            self.last_side = requested
            return requested

        margin = settings["auto_side_margin"]
        lost_min = settings["lost_wall_min_portion"]

        if max(left_portion, right_portion) < lost_min:
            return self.last_side

        if self.last_side == "LEFT":
            if right_portion > left_portion + margin * 1.4:
                self.last_side = "RIGHT"
        elif left_portion > right_portion + margin * 1.4:
            self.last_side = "LEFT"

        if abs(left_portion - right_portion) > margin:
            self.last_side = "LEFT" if left_portion > right_portion else "RIGHT"

        return self.last_side

    def compute(self, roi_bgr, draw_frame, roi_y_offset, settings):
        wall_mask = self.make_wall_mask(roi_bgr, settings)
        h, w = wall_mask.shape
        band_w = max(1, int(w * settings["side_band_portion"]))
        y0 = int(h * settings["analysis_start_portion"])

        left_roi = wall_mask[y0:, :band_w]
        right_roi = wall_mask[y0:, w - band_w:]
        raw_left = cv2.countNonZero(left_roi) / max(1, left_roi.size)
        raw_right = cv2.countNonZero(right_roi) / max(1, right_roi.size)

        alpha = 0.35
        self.smooth_left = alpha * raw_left + (1.0 - alpha) * self.smooth_left
        self.smooth_right = alpha * raw_right + (1.0 - alpha) * self.smooth_right
        left_portion = self.smooth_left
        right_portion = self.smooth_right

        side = self.select_side(left_portion, right_portion, settings)
        target = settings["wall_target_portion"]
        lost = max(left_portion, right_portion) < settings["lost_wall_min_portion"]
        emergency_side = None
        mode = f"follow {side.lower()}"

        if left_portion >= settings["emergency_wall_portion"] and left_portion > right_portion:
            side = "LEFT"
            emergency_side = "LEFT"
            mode = "avoid left"
        elif right_portion >= settings["emergency_wall_portion"] and right_portion > left_portion:
            side = "RIGHT"
            emergency_side = "RIGHT"
            mode = "avoid right"
        elif left_portion > target and right_portion > target:
            mode = "center"

        if lost:
            mode = "lost wall"
            steering = 0
            speed = 0 if settings["lost_wall_stop"] else settings["min_speed"]
            error = 0.0
        else:
            if mode == "center":
                error = left_portion - right_portion
                correction = settings["center_kp"] * error
                steering = -correction
            else:
                active_portion = left_portion if side == "LEFT" else right_portion
                error = active_portion - target
                now = time.monotonic()
                if self.last_time is None or self.last_mode != mode:
                    dt = 0.05
                    derivative = 0.0
                else:
                    dt = clamp(now - self.last_time, 0.02, 0.2)
                    derivative = (error - self.last_error) / dt
                correction = settings["wall_kp"] * error + settings["wall_kd"] * derivative
                steering = -correction if side == "LEFT" else correction

            steering *= settings["steering_sign"]
            steering = int(clamp(round(steering), -settings["max_steer"], settings["max_steer"]))

            base_speed = settings["base_speed"]
            if emergency_side:
                base_speed = min(base_speed, settings["min_speed"])
            elif abs(steering) > 30:
                base_speed -= 45
            elif abs(steering) > 18:
                base_speed -= 25
            elif abs(steering) > 10:
                base_speed -= 10
            speed = int(clamp(base_speed, settings["min_speed"], settings["max_speed"]))

        self.last_error = error
        self.last_time = time.monotonic()
        self.last_mode = mode

        if settings["debug_overlay"]:
            self.draw_debug(
                draw_frame,
                wall_mask,
                roi_y_offset,
                y0,
                band_w,
                left_portion,
                right_portion,
                target,
                side,
                mode,
                steering,
                speed,
            )

        return {
            "steering": steering,
            "speed": speed,
            "side": side,
            "mode": mode,
            "left_portion": left_portion,
            "right_portion": right_portion,
            "wall_mask": wall_mask,
        }

    def draw_debug(
        self,
        draw_frame,
        wall_mask,
        roi_y_offset,
        y0,
        band_w,
        left_portion,
        right_portion,
        target,
        side,
        mode,
        steering,
        speed,
    ):
        h, w = wall_mask.shape
        roi_view = draw_frame[roi_y_offset:roi_y_offset + h, :]

        colored = roi_view.copy()
        colored[wall_mask > 0] = (0, 90, 255)
        cv2.addWeighted(colored, 0.38, roi_view, 0.62, 0, roi_view)

        contours, _ = cv2.findContours(wall_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(roi_view, contours, -1, (0, 255, 255), 1)

        roi_top = roi_y_offset + y0
        roi_bottom = roi_y_offset + h - 1
        left_color = (0, 255, 255) if side == "LEFT" else (80, 220, 80)
        right_color = (0, 255, 255) if side == "RIGHT" else (80, 220, 80)
        cv2.rectangle(draw_frame, (0, roi_top), (band_w, roi_bottom), left_color, 2)
        cv2.rectangle(draw_frame, (w - band_w, roi_top), (w - 1, roi_bottom), right_color, 2)
        cv2.line(draw_frame, (0, roi_y_offset), (w, roi_y_offset), (255, 255, 255), 1)
        cv2.line(draw_frame, (0, roi_top), (w, roi_top), (170, 170, 170), 1)

        cv2.putText(
            draw_frame,
            f"{mode.upper()}  side={side}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            draw_frame,
            f"L={left_portion:.3f} R={right_portion:.3f} target={target:.2f}",
            (10, 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            draw_frame,
            f"steer={steering:+d} speed={speed}",
            (10, 72),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )

        self.draw_portion_bar(draw_frame, "L", left_portion, 10, 92, (0, 220, 255))
        self.draw_portion_bar(draw_frame, "R", right_portion, 10, 112, (0, 220, 255))

        mini_w = 150
        mini_h = max(1, int(h * mini_w / max(1, w)))
        mini_mask = cv2.resize(wall_mask, (mini_w, mini_h), interpolation=cv2.INTER_NEAREST)
        mini_bgr = cv2.cvtColor(mini_mask, cv2.COLOR_GRAY2BGR)
        x1 = w - mini_w - 10
        y1 = 10
        draw_frame[y1:y1 + mini_h, x1:x1 + mini_w] = mini_bgr
        cv2.rectangle(draw_frame, (x1, y1), (x1 + mini_w, y1 + mini_h), (255, 255, 255), 1)
        cv2.putText(
            draw_frame,
            "wall mask",
            (x1, y1 + mini_h + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    @staticmethod
    def draw_portion_bar(draw_frame, label, portion, x, y, color):
        bar_w = 120
        bar_h = 10
        cv2.putText(
            draw_frame,
            label,
            (x, y + 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(draw_frame, (x + 18, y), (x + 18 + bar_w, y + bar_h), (80, 80, 80), 1)
        fill = int(clamp(portion, 0.0, 1.0) * bar_w)
        if fill > 0:
            cv2.rectangle(draw_frame, (x + 19, y + 1), (x + 18 + fill, y + bar_h - 1), color, -1)


load_config()
wall_follower = WallFollower()


def process_frame(frame, arduino):
    if frame is None:
        return None

    snapshot = get_config_snapshot()
    tracking = snapshot["tracking"]
    settings = snapshot["camera"]
    serial_cfg = snapshot["serial"]

    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    flip_code = settings.get("flip_code")
    if flip_code in (0, 1, -1):
        frame_bgr = cv2.flip(frame_bgr, int(flip_code))

    crop_height = int(clamp(settings["crop_height"], 0, frame_bgr.shape[0] - 2))
    display_frame = frame_bgr.copy()
    roi = display_frame[crop_height:, :].copy()

    control = {
        "steering": 0,
        "speed": 0,
        "side": wall_follower.last_side,
        "mode": "walls off",
        "left_portion": 0.0,
        "right_portion": 0.0,
    }

    if tracking.get("WALLS", True) and roi.size:
        control = wall_follower.compute(roi, display_frame, crop_height, settings)

    drive_speed = 0
    if tracking.get("WALLS", True) and settings["drive_enabled"]:
        drive_speed = int(serial_cfg["drive_sign"] * control["speed"])

    if arduino:
        arduino.update(control["steering"], drive_speed)

    if not settings["debug_overlay"]:
        cv2.line(display_frame, (0, crop_height), (frame_bgr.shape[1], crop_height), (255, 255, 255), 1)

    update_runtime_status(
        mode=control["mode"],
        side=control["side"],
        left_portion=round(control["left_portion"], 4),
        right_portion=round(control["right_portion"], 4),
        steering=int(control["steering"]),
        speed=int(drive_speed),
    )

    return display_frame


def camera_loop():
    global output_frame
    arduino = None
    picam2 = None
    frame_count = 0
    fps_start = time.monotonic()

    try:
        snapshot = get_config_snapshot()
        arduino = ArduinoController(snapshot["serial"])

        if Picamera2 is None:
            raise RuntimeError("Picamera2 is not installed. Run this on the Raspberry Pi camera environment.")

        picam2 = Picamera2()
        config = picam2.create_preview_configuration(main={"size": FRAME_SIZE, "format": "RGB888"})
        picam2.configure(config)
        picam2.start()
        update_runtime_status(camera="running", message="")
        print("Camera started successfully.")

        while not stop_event.is_set():
            frame = picam2.capture_array()
            if frame is None:
                time.sleep(0.01)
                continue

            processed = process_frame(frame, arduino)
            if processed is None:
                time.sleep(0.01)
                continue

            quality = get_config_snapshot()["camera"]["jpeg_quality"]
            ok, encoded = cv2.imencode(".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if ok:
                with output_lock:
                    output_frame = encoded.tobytes()

            frame_count += 1
            now = time.monotonic()
            if now - fps_start >= 1.0:
                update_runtime_status(fps=round(frame_count / (now - fps_start), 1))
                frame_count = 0
                fps_start = now

    except Exception as exc:
        message = f"Camera error: {exc}"
        update_runtime_status(camera="error", message=str(exc), mode="camera error", speed=0)
        with output_lock:
            output_frame = make_text_frame([message, "Open the tuner page for settings/status."], (80, 180, 255))
        print(f"FATAL CAMERA ERROR: {exc}")
    finally:
        try:
            if arduino:
                arduino.stop()
                arduino.close()
        except Exception:
            pass
        try:
            if picam2:
                picam2.stop()
        except Exception:
            pass


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Wall Follow Tuner</title>
    <style>
        :root {
            color-scheme: dark;
            --bg: #090b0d;
            --panel: #14181c;
            --panel-2: #1b2026;
            --line: #2a3038;
            --text: #edf2f7;
            --muted: #9aa7b4;
            --accent: #10b981;
            --warn: #f59e0b;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        main {
            width: min(1120px, calc(100vw - 28px));
            margin: 0 auto;
            padding: 24px 0 32px;
            display: grid;
            grid-template-columns: minmax(320px, 640px) minmax(290px, 1fr);
            gap: 18px;
            align-items: start;
        }
        .video-feed {
            width: 100%;
            aspect-ratio: 4 / 3;
            object-fit: contain;
            display: block;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: #050505;
        }
        .panel {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 16px;
        }
        .stack { display: grid; gap: 14px; }
        .topline {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }
        h1 {
            margin: 0;
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 0;
        }
        .status {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 8px;
        }
        .stat {
            background: var(--panel-2);
            border: 1px solid var(--line);
            border-radius: 6px;
            padding: 9px 10px;
            min-height: 58px;
        }
        .stat span {
            display: block;
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            font-weight: 700;
            letter-spacing: 0.4px;
            margin-bottom: 4px;
        }
        .stat strong {
            font-size: 17px;
            line-height: 1.1;
            word-break: break-word;
        }
        .section {
            border-top: 1px solid var(--line);
            padding-top: 14px;
            display: grid;
            gap: 12px;
        }
        .section:first-child {
            border-top: none;
            padding-top: 0;
        }
        .section-title {
            margin: 0;
            color: var(--muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 800;
        }
        .control-row {
            display: grid;
            grid-template-columns: 142px minmax(0, 1fr) 54px;
            gap: 10px;
            align-items: center;
        }
        .control-row label {
            color: var(--text);
            font-size: 13px;
            font-weight: 650;
        }
        input[type="range"] {
            width: 100%;
            accent-color: var(--accent);
        }
        input[type="checkbox"] {
            width: 19px;
            height: 19px;
            accent-color: var(--accent);
        }
        select, button {
            min-height: 36px;
            background: var(--panel-2);
            color: var(--text);
            border: 1px solid var(--line);
            border-radius: 5px;
            padding: 7px 10px;
            font-size: 13px;
        }
        button {
            background: #e5e7eb;
            color: #050505;
            font-weight: 750;
            cursor: pointer;
        }
        button:hover { background: #ffffff; }
        .value {
            color: var(--muted);
            font-size: 12px;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }
        .inline {
            display: flex;
            flex-wrap: wrap;
            gap: 10px 18px;
            align-items: center;
        }
        .check {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            font-weight: 650;
        }
        .message {
            color: var(--warn);
            font-size: 13px;
            min-height: 18px;
            word-break: break-word;
        }
        @media (max-width: 920px) {
            main { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <main>
        <section>
            <div class="topline">
                <h1>Wall Follow Tuner</h1>
                <button type="button" onclick="saveConfig()">Save</button>
            </div>
            <img src="/video_feed" class="video-feed" alt="Camera feed">
        </section>

        <aside class="stack">
            <section class="panel stack">
                <div class="status">
                    <div class="stat"><span>Mode</span><strong id="mode">-</strong></div>
                    <div class="stat"><span>Side</span><strong id="side">-</strong></div>
                    <div class="stat"><span>FPS</span><strong id="fps">-</strong></div>
                    <div class="stat"><span>Left</span><strong id="left">0.000</strong></div>
                    <div class="stat"><span>Right</span><strong id="right">0.000</strong></div>
                    <div class="stat"><span>Steer</span><strong id="steer">0</strong></div>
                </div>
                <div class="message" id="message"></div>
            </section>

            <section class="panel stack">
                <div class="section">
                    <p class="section-title">Run</p>
                    <div class="inline">
                        <label class="check"><input type="checkbox" id="drive_enabled" onchange="updateCameraBool('drive_enabled')"> Drive</label>
                        <label class="check"><input type="checkbox" id="track_WALLS" onchange="toggleTracking('WALLS')"> Walls</label>
                        <label class="check"><input type="checkbox" id="debug_overlay" onchange="updateCameraBool('debug_overlay')"> Debug</label>
                        <select id="follow_side" onchange="updateCameraValue('follow_side', this.value)">
                            <option value="AUTO">AUTO</option>
                            <option value="LEFT">LEFT</option>
                            <option value="RIGHT">RIGHT</option>
                        </select>
                    </div>
                </div>

                <div class="section">
                    <p class="section-title">Vision</p>
                    <div class="control-row">
                        <label for="crop_height">Crop</label>
                        <input type="range" id="crop_height" min="0" max="420" step="1" oninput="updateCameraRange('crop_height')">
                        <span class="value" id="crop_height_value">0</span>
                    </div>
                    <div class="control-row">
                        <label for="gray_thresh">Gray</label>
                        <input type="range" id="gray_thresh" min="0" max="255" step="1" oninput="updateCameraRange('gray_thresh')">
                        <span class="value" id="gray_thresh_value">0</span>
                    </div>
                    <div class="control-row">
                        <label for="target">Target</label>
                        <input type="range" id="wall_target_portion" min="0.05" max="0.90" step="0.01" oninput="updateCameraRange('wall_target_portion')">
                        <span class="value" id="wall_target_portion_value">0</span>
                    </div>
                </div>

                <div class="section">
                    <p class="section-title">Control</p>
                    <div class="control-row">
                        <label for="wall_kp">Kp</label>
                        <input type="range" id="wall_kp" min="0" max="300" step="1" oninput="updateCameraRange('wall_kp')">
                        <span class="value" id="wall_kp_value">0</span>
                    </div>
                    <div class="control-row">
                        <label for="wall_kd">Kd</label>
                        <input type="range" id="wall_kd" min="0" max="50" step="0.5" oninput="updateCameraRange('wall_kd')">
                        <span class="value" id="wall_kd_value">0</span>
                    </div>
                    <div class="control-row">
                        <label for="base_speed">Speed</label>
                        <input type="range" id="base_speed" min="0" max="255" step="1" oninput="updateCameraRange('base_speed')">
                        <span class="value" id="base_speed_value">0</span>
                    </div>
                </div>
            </section>
        </aside>
    </main>

    <script>
        const initialCamera = {{ camera_json | safe }};
        const initialTracking = {{ tracking_json | safe }};
        const pendingTimers = {};

        function setValue(id, value) {
            const el = document.getElementById(id);
            const label = document.getElementById(id + '_value');
            if (!el) return;
            el.value = value;
            if (label) label.textContent = value;
        }

        function postJSON(url, data) {
            return fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
        }

        function updateCameraValue(key, value) {
            postJSON('/update_camera', {[key]: value});
        }

        function updateCameraBool(key) {
            const el = document.getElementById(key);
            updateCameraValue(key, el.checked);
        }

        function updateCameraRange(key) {
            const el = document.getElementById(key);
            const valueEl = document.getElementById(key + '_value');
            if (valueEl) valueEl.textContent = el.value;
            clearTimeout(pendingTimers[key]);
            pendingTimers[key] = setTimeout(() => {
                const value = el.step && el.step.includes('.') ? parseFloat(el.value) : Number(el.value);
                updateCameraValue(key, value);
            }, 80);
        }

        function toggleTracking(name) {
            const el = document.getElementById('track_' + name);
            postJSON('/toggle_color', {colorName: name, state: el.checked});
        }

        function saveConfig() {
            postJSON('/save_config', {}).then(() => {
                const msg = document.getElementById('message');
                msg.textContent = 'Saved.';
                setTimeout(() => { if (msg.textContent === 'Saved.') msg.textContent = ''; }, 1200);
            });
        }

        function loadInitial() {
            ['crop_height', 'gray_thresh', 'wall_target_portion', 'wall_kp', 'wall_kd', 'base_speed'].forEach(key => {
                setValue(key, initialCamera[key]);
            });
            document.getElementById('follow_side').value = initialCamera.follow_side || 'AUTO';
            document.getElementById('drive_enabled').checked = initialCamera.drive_enabled !== false;
            document.getElementById('debug_overlay').checked = initialCamera.debug_overlay !== false;
            document.getElementById('track_WALLS').checked = initialTracking.WALLS !== false;
        }

        function refreshStatus() {
            fetch('/status')
                .then(resp => resp.json())
                .then(data => {
                    document.getElementById('mode').textContent = data.mode || '-';
                    document.getElementById('side').textContent = data.side || '-';
                    document.getElementById('fps').textContent = data.fps ?? '-';
                    document.getElementById('left').textContent = Number(data.left_portion || 0).toFixed(3);
                    document.getElementById('right').textContent = Number(data.right_portion || 0).toFixed(3);
                    document.getElementById('steer').textContent = String(data.steering || 0);
                    if (data.message) document.getElementById('message').textContent = data.message;
                })
                .catch(() => {});
        }

        window.addEventListener('load', () => {
            loadInitial();
            refreshStatus();
            setInterval(refreshStatus, 600);
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    snapshot = get_config_snapshot()
    return render_template_string(
        HTML_TEMPLATE,
        camera_json=json.dumps(snapshot["camera"]),
        tracking_json=json.dumps(snapshot["tracking"]),
    )


@app.route("/status")
def status():
    return jsonify(get_runtime_status())


@app.route("/update_camera", methods=["POST"])
def update_camera():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "invalid JSON"}), 400

    with config_lock:
        camera_settings.update(data)
        normalized = normalize_camera_settings(camera_settings)
        camera_settings.clear()
        camera_settings.update(normalized)

    return jsonify({"status": "success", "camera": get_config_snapshot()["camera"]})


@app.route("/update_color", methods=["POST"])
def update_color():
    data = request.get_json(silent=True) or {}
    name = data.get("colorName")
    hex_lo = data.get("lowHex")
    hex_hi = data.get("highHex")
    if not name or not hex_lo or not hex_hi:
        return jsonify({"status": "error", "message": "missing fields"}), 400

    h1, s1, v1 = hex_to_hsv(hex_lo)
    h2, s2, v2 = hex_to_hsv(hex_hi)

    h_min = max(0, min(h1, h2) - 6)
    h_max = min(179, max(h1, h2) + 6)
    s_min = max(40, min(s1, s2) - 20)
    v_min = max(20, min(v1, v2) - 30)

    with config_lock:
        current_colors[f"{name}LO"] = [int(h_min), int(s_min), int(v_min)]
        current_colors[f"{name}HI"] = [int(h_max), 255, 255]
        current_colors[f"{name}_HEX_LO"] = hex_lo
        current_colors[f"{name}_HEX_HI"] = hex_hi
    save_all_to_disk()

    return jsonify({"status": "success"})


@app.route("/toggle_color", methods=["POST"])
def toggle_color():
    data = request.get_json(silent=True) or {}
    color_name = data.get("colorName")
    state = data.get("state", False)

    if not color_name:
        return jsonify({"status": "error", "message": "missing colorName"}), 400

    with config_lock:
        current_tracking[str(color_name).upper()] = to_bool(state, False)
    save_all_to_disk()

    return jsonify({"status": "success", "state": to_bool(state, False)})


@app.route("/save_config", methods=["POST"])
def save_config():
    save_all_to_disk()
    return jsonify({"status": "saved"})


def generate():
    placeholder = make_text_frame("Waiting for camera...")
    frame_delay = 1.0 / STREAM_FPS

    while not stop_event.is_set():
        with output_lock:
            frame_data = output_frame

        if frame_data is None:
            frame_data = placeholder

        if frame_data:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                frame_data +
                b"\r\n"
            )
        time.sleep(frame_delay)


@app.route("/video_feed")
def video_feed():
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    threading.Thread(target=camera_loop, daemon=True).start()

    if DEBUG and AUTO_OPEN_BROWSER:
        threading.Thread(
            target=lambda: (time.sleep(2), webbrowser.open("http://127.0.0.1:5000")),
            daemon=True,
        ).start()

    try:
        app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)
    finally:
        stop_event.set()
