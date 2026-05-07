import os
import json
import time
import serial
import cv2
import numpy as np
import threading
import webbrowser
from flask import Flask, Response, render_template_string, request, jsonify
from picamera2 import Picamera2

# --- CONFIGURATION ---
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600
DEBUG = True
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

FRAME_SIZE = (640, 480)
DEFAULT_CROP_HEIGHT = 200

# Wall following tuneables
WALL_TARGET_PORTION = 0.45   # close to the repo's fixed-reference approach
WALL_KP = 100.0
WALL_KD = 40.0
BASE_SPEED = 220
MIN_SPEED = 200
MAX_SPEED = 230
MAX_STEER = 45

# If your motor is still backwards, set this to -1
DRIVE_SIGN = -1

# --- SHARED STATE ---
output_frame = None
lock = threading.Lock()
config_lock = threading.Lock()
camera_ready = threading.Event()
app = Flask(__name__)

current_colors = {
    "REDLO": [0, 100, 80], "REDHI": [10, 255, 255],
    "RED_HEX_LO": "#5a0000", "RED_HEX_HI": "#ff0000",
    "GREENLO": [40, 40, 30], "GREENHI": [85, 255, 255],
    "GREEN_HEX_LO": "#002800", "GREEN_HEX_HI": "#00ff00",
    "ORANGELO": [7, 20, 10], "ORANGEHI": [37, 255, 255],
    "ORANGE_HEX_LO": "#5a2800", "ORANGE_HEX_HI": "#ff8c00",
    "BLUELO": [100, 85, 90], "BLUEHI": [130, 255, 255],
    "BLUE_HEX_LO": "#00005a", "BLUE_HEX_HI": "#0000ff",
    "PINKLO": [158, 160, 100], "PINKHI": [170, 255, 255],
    "PINK_HEX_LO": "#5a0028", "PINK_HEX_HI": "#ff00ff",
}
current_tracking = {
    "RED": True, "GREEN": True, "ORANGE": True, "BLUE": True, "PINK": True,
    "WALLS": True
}
camera_settings = {
    "crop_height": DEFAULT_CROP_HEIGHT,
    "gray_thresh": 110,
    "follow_side": "AUTO",     # AUTO / LEFT / RIGHT
    "wall_target_portion": WALL_TARGET_PORTION,
    "wall_kp": WALL_KP,
    "wall_kd": WALL_KD,
    "base_speed": BASE_SPEED,
    "flip_code": -1,         # set to 0, 1, or -1 if your camera is mounted flipped
}

last_wall_error = 0.0
last_wall_side = "LEFT"

def clamp(value, lo, hi):
    return max(lo, min(hi, value))

def hex_to_hsv(hex_str):
    hex_str = (hex_str or "").lstrip("#")
    if len(hex_str) != 6:
        return [0, 0, 0]
    r, g, b = tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
    hsv_img = cv2.cvtColor(np.uint8([[[r, g, b]]]), cv2.COLOR_RGB2HSV)
    return [int(x) for x in hsv_img[0][0]]

def hsv_to_hex(h, s, v):
    rgb_img = cv2.cvtColor(np.uint8([[[int(h), int(s), int(v)]]]), cv2.COLOR_HSV2RGB)
    r, g, b = rgb_img[0][0]
    return f"#{r:02x}{g:02x}{b:02x}"

def init_config():
    global current_colors, current_tracking, camera_settings
    if not os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        with config_lock:
            if "colors" in cfg and isinstance(cfg["colors"], dict):
                current_colors.update(cfg["colors"])
            if "tracking" in cfg and isinstance(cfg["tracking"], dict):
                current_tracking.update(cfg["tracking"])
            if "camera" in cfg and isinstance(cfg["camera"], dict):
                camera_settings.update(cfg["camera"])

            for c in ["RED", "GREEN", "ORANGE", "BLUE", "PINK"]:
                if f"{c}LO" in current_colors and f"{c}_HEX_LO" not in current_colors:
                    current_colors[f"{c}_HEX_LO"] = hsv_to_hex(*current_colors[f"{c}LO"])
                if f"{c}HI" in current_colors and f"{c}_HEX_HI" not in current_colors:
                    current_colors[f"{c}_HEX_HI"] = hsv_to_hex(*current_colors[f"{c}HI"])
    except Exception as e:
        print(f"Error loading config: {e}")

def save_all_to_disk():
    with config_lock:
        cfg = {
            "colors": current_colors,
            "tracking": current_tracking,
            "camera": camera_settings,
        }
        tmp_path = CONFIG_PATH + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(cfg, f, indent=4)
            os.replace(tmp_path, CONFIG_PATH)
        except Exception as e:
            print(f"Failed to save config: {e}")

init_config()

class ArduinoController:
    def __init__(self, port: str, baud_rate: int):
        try:
            self.ser = serial.Serial(port=port, baudrate=baud_rate, timeout=0.2, write_timeout=0.2)
            time.sleep(2)
            self.ser.reset_input_buffer()
        except Exception as e:
            print(f"Arduino Warning: {e}")
            self.ser = None

    def send_command(self, command: str) -> None:
        if not self.ser:
            return
        try:
            self.ser.write(f"{command}\n".encode("ascii"))
            self.ser.flush()
        except Exception as e:
            print(f"Arduino send error: {e}")

    def steer(self, angle: int) -> None:
        self.send_command(f"STEER:{int(angle)}")

    def drive(self, speed: int) -> None:
        speed = max(-255, min(255, int(speed)))
        self.send_command(f"DRIVE:{speed}")

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()

def make_placeholder_frame():
    img = np.zeros((FRAME_SIZE[1], FRAME_SIZE[0], 3), dtype=np.uint8)
    cv2.putText(img, "Waiting for camera...", (170, 235),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    ok, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes() if ok else None

def follow_wall_control(roi_bgr, draw_frame, roi_y_offset):
    global last_wall_error, last_wall_side

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray_thresh = int(camera_settings.get("gray_thresh", 110))
    _, wall_mask = cv2.threshold(gray, gray_thresh, 255, cv2.THRESH_BINARY_INV)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    wall_mask = cv2.morphologyEx(wall_mask, cv2.MORPH_OPEN, kernel)
    wall_mask = cv2.morphologyEx(wall_mask, cv2.MORPH_CLOSE, kernel)

    h, w = wall_mask.shape
    y0 = int(h * 0.15)

    left_roi = wall_mask[y0:, : int(w * 0.28)]
    right_roi = wall_mask[y0:, int(w * 0.72):]

    left_portion = cv2.countNonZero(left_roi) / max(1, left_roi.size)
    right_portion = cv2.countNonZero(right_roi) / max(1, right_roi.size)

    side = str(camera_settings.get("follow_side", "AUTO")).upper()
    if side == "AUTO":
        if left_portion > right_portion + 0.05:
            side = "LEFT"
        elif right_portion > left_portion + 0.05:
            side = "RIGHT"
        else:
            side = last_wall_side

    last_wall_side = side

    target = float(camera_settings.get("wall_target_portion", WALL_TARGET_PORTION))
    kp = float(camera_settings.get("wall_kp", WALL_KP))
    kd = float(camera_settings.get("wall_kd", WALL_KD))

    if side == "LEFT":
        error = left_portion - target
        correction = kp * error + kd * (error - last_wall_error)
        steering_angle = -correction
    else:
        error = right_portion - target
        correction = kp * error + kd * (error - last_wall_error)
        steering_angle = correction

    last_wall_error = error
    steering_angle = int(clamp(steering_angle, -MAX_STEER, MAX_STEER))

    base_speed = int(camera_settings.get("base_speed", BASE_SPEED))
    if abs(steering_angle) > 28:
        base_speed -= 35
    elif abs(steering_angle) > 15:
        base_speed -= 15
    speed = int(clamp(base_speed, MIN_SPEED, MAX_SPEED))

    # Draw overlays
    roi_top = roi_y_offset
    roi_bottom = roi_y_offset + h
    cv2.rectangle(draw_frame, (0, roi_top), (int(w * 0.28), roi_bottom), (0, 255, 0), 1)
    cv2.rectangle(draw_frame, (int(w * 0.72), roi_top), (w - 1, roi_bottom), (0, 255, 0), 1)
    cv2.line(draw_frame, (0, roi_y_offset + y0), (w, roi_y_offset + y0), (255, 255, 255), 1)

    cv2.putText(draw_frame, f"Wall side: {side}", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    cv2.putText(draw_frame, f"L={left_portion:.3f} R={right_portion:.3f} T={target:.2f}",
                (10, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(draw_frame, f"Steer={steering_angle:+d} Speed={speed}",
                (10, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)

    return steering_angle, speed, wall_mask

def process_frame(frame, arduino):
    try:
        if frame is None:
            return None

        # Picamera2 preview frames should be RGB888 here
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        flip_code = camera_settings.get("flip_code", None)
        if flip_code in (0, 1, -1):
            frame = cv2.flip(frame, int(flip_code))

        crop_height = int(camera_settings.get("crop_height", DEFAULT_CROP_HEIGHT))
        crop_height = clamp(crop_height, 0, frame.shape[0] - 2)

        display_frame = frame.copy()
        roi = display_frame[crop_height:, :].copy()

        # Wall following
        if current_tracking.get("WALLS", True) and roi.size:
            steering_angle, speed, wall_mask = follow_wall_control(roi, display_frame, crop_height)
            if arduino:
                arduino.steer(steering_angle)
                arduino.drive(int(DRIVE_SIGN * speed))
        else:
            if arduino:
                arduino.steer(0)
                arduino.drive(0)

        # Optional color-tracking cleanup remains possible here
        cv2.line(display_frame, (0, crop_height), (frame.shape[1], crop_height), (255, 255, 255), 1)

        return display_frame

    except Exception as e:
        print(f"Vision Processing Error: {e}")
        return frame

def camera_loop():
    global output_frame
    arduino = None
    picam2 = None
    try:
        arduino = ArduinoController(SERIAL_PORT, BAUD_RATE)

        picam2 = Picamera2()
        config = picam2.create_preview_configuration(
            main={"size": FRAME_SIZE, "format": "RGB888"}
        )
        picam2.configure(config)
        picam2.start()
        camera_ready.set()
        print("Camera started successfully.")

        while True:
            frame = picam2.capture_array()
            if frame is None:
                time.sleep(0.01)
                continue

            processed = process_frame(frame, arduino)
            if processed is None:
                time.sleep(0.01)
                continue

            ok, encoded = cv2.imencode(".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                with lock:
                    output_frame = encoded.tobytes()
            else:
                time.sleep(0.005)

    except Exception as e:
        print(f"FATAL CAMERA ERROR: {e}")
    finally:
        try:
            if arduino:
                arduino.drive(0)
                arduino.steer(0)
                arduino.close()
        except Exception:
            pass
        try:
            if picam2:
                picam2.stop()
        except Exception:
            pass

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Vision Tuner</title>
    <style>
        body { background: #0a0a0a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; flex-direction: column; align-items: center; margin: 0; padding: 40px 20px; }
        .container { width: 640px; }
        .video-feed { width: 100%; border-radius: 6px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); display: block; margin-bottom: 24px; min-height: 480px; background: #111; }
        .controls { background: #141414; border-radius: 6px; padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; border: 1px solid #222; }
        .row { display: flex; justify-content: space-between; align-items: center; }
        .group { display: flex; align-items: center; gap: 12px; }
        label.section-title { font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
        select { background: #1e1e1e; color: #fff; border: 1px solid #333; border-radius: 4px; padding: 6px 12px; font-size: 14px; cursor: pointer; outline: none; }
        input[type="color"] { background: transparent; border: none; width: 36px; height: 36px; padding: 0; cursor: pointer; border-radius: 4px; overflow: hidden; }
        input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; }
        input[type="color"]::-webkit-color-swatch { border: 1px solid #444; border-radius: 4px; }
        button { background: #e0e0e0; color: #000; border: none; padding: 8px 16px; border-radius: 4px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
        button:hover { background: #fff; }
        #status { font-size: 12px; color: #4ade80; opacity: 0; transition: opacity 0.3s; font-weight: 600; }
        .toggles-container { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; }
        .toggle-item { display: flex; align-items: center; justify-content: space-between; background: #1e1e1e; padding: 8px 14px; border-radius: 8px; border: 1px solid #333; min-width: 90px; }
        .toggle-item span { font-size: 13px; font-weight: 600; color: #eee; }
        input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; accent-color: #2ea043; }
    </style>
</head>
<body>
    <div class="container">
        <img src="/video_feed" class="video-feed" id="video" alt="Loading Camera Feed..." />
        <div class="controls">
            <div class="row">
                <div class="group">
                    <label class="section-title">Target Object</label>
                    <select id="colorSelect" onchange="loadSelectedColor()">
                        <option value="RED">Red</option>
                        <option value="GREEN" selected>Green</option>
                        <option value="ORANGE">Orange</option>
                        <option value="BLUE">Blue</option>
                        <option value="PINK">Pink</option>
                    </select>
                </div>
                <div class="group">
                    <span id="status">Saved.</span>
                    <button onclick="saveConfig()">Save Colors</button>
                </div>
            </div>

            <div class="row" style="justify-content: flex-start; gap: 40px; border-top: 1px solid #222; padding-top: 16px;">
                <div class="group">
                    <label class="section-title">Darkest Point</label>
                    <input type="color" id="colorLow" onchange="updateColors()">
                </div>
                <div class="group">
                    <label class="section-title">Brightest Point</label>
                    <input type="color" id="colorHigh" onchange="updateColors()">
                </div>
            </div>

            <div style="border-top: 1px solid #222; padding-top: 16px; display: flex; flex-direction: column;">
                <label class="section-title">Active Tracking</label>
                <div class="toggles-container">
                    <label class="toggle-item"><span>RED</span><input type="checkbox" id="track_RED" onchange="toggleColor('RED')"></label>
                    <label class="toggle-item"><span>GREEN</span><input type="checkbox" id="track_GREEN" onchange="toggleColor('GREEN')"></label>
                    <label class="toggle-item"><span>ORANGE</span><input type="checkbox" id="track_ORANGE" onchange="toggleColor('ORANGE')"></label>
                    <label class="toggle-item"><span>BLUE</span><input type="checkbox" id="track_BLUE" onchange="toggleColor('BLUE')"></label>
                    <label class="toggle-item"><span>PINK</span><input type="checkbox" id="track_PINK" onchange="toggleColor('PINK')"></label>
                    <label class="toggle-item"><span>WALLS</span><input type="checkbox" id="track_WALLS" onchange="toggleColor('WALLS')"></label>
                </div>
            </div>
        </div>
    </div>

    <script>
        const configData = {{ colors_json | safe }};
        const trackingData = {{ tracking_json | safe }};

        function loadSelectedColor() {
            const color = document.getElementById("colorSelect").value;
            document.getElementById("colorLow").value = configData[color + "_HEX_LO"] || "#000000";
            document.getElementById("colorHigh").value = configData[color + "_HEX_HI"] || "#ffffff";
        }

        function initToggles() {
            ['RED', 'GREEN', 'ORANGE', 'BLUE', 'PINK', 'WALLS'].forEach(c => {
                const el = document.getElementById('track_' + c);
                if (el) el.checked = (trackingData[c] !== false);
            });
        }

        function updateColors() {
            const color = document.getElementById("colorSelect").value;
            const data = {
                colorName: color,
                lowHex: document.getElementById("colorLow").value,
                highHex: document.getElementById("colorHigh").value
            };

            configData[color + "_HEX_LO"] = data.lowHex;
            configData[color + "_HEX_HI"] = data.highHex;

            fetch('/update_color', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
        }

        function toggleColor(color) {
            const checkbox = document.getElementById('track_' + color);
            const isChecked = checkbox.checked;
            trackingData[color] = isChecked;

            fetch('/toggle_color', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ colorName: color, state: isChecked })
            });
        }

        function saveConfig() {
            fetch('/save_config', { method: 'POST' }).then(() => {
                const status = document.getElementById('status');
                status.style.opacity = 1;
                setTimeout(() => status.style.opacity = 0, 2000);
            });
        }

        window.onload = () => {
            loadSelectedColor();
            initToggles();
        };
    </script>
</body>
</html>
'''

@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        colors_json=json.dumps(current_colors),
        tracking_json=json.dumps(current_tracking)
    )

@app.route("/update_color", methods=["POST"])
def update_color():
    global current_colors
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
    s_min = max(100, min(s1, s2) - 20)
    s_max = 255
    v_min = max(40, min(v1, v2) - 30)
    v_max = 255

    with config_lock:
        current_colors[f"{name}LO"] = [int(h_min), int(s_min), int(v_min)]
        current_colors[f"{name}HI"] = [int(h_max), int(s_max), int(v_max)]
        current_colors[f"{name}_HEX_LO"] = hex_lo
        current_colors[f"{name}_HEX_HI"] = hex_hi
    save_all_to_disk()

    return jsonify({"status": "success"})

@app.route("/toggle_color", methods=["POST"])
def toggle_color():
    global current_tracking
    data = request.get_json(silent=True) or {}
    color_name = data.get("colorName")
    state = data.get("state", False)

    if not color_name:
        return jsonify({"status": "error", "message": "missing colorName"}), 400

    if isinstance(state, str):
        state = state.lower() in ("true", "1", "yes", "on")

    with config_lock:
        current_tracking[color_name] = bool(state)
    save_all_to_disk()

    return jsonify({"status": "success", "state": bool(state)})

@app.route("/save_config", methods=["POST"])
def save_config():
    save_all_to_disk()
    return jsonify({"status": "saved"})

def generate():
    global output_frame
    placeholder = make_placeholder_frame()

    while True:
        with lock:
            frame_data = output_frame

        if frame_data is None:
            frame_data = placeholder
            time.sleep(0.05)

        if frame_data is None:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" +
            frame_data +
            b"\r\n"
        )

@app.route("/video_feed")
def video_feed():
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    threading.Thread(target=camera_loop, daemon=True).start()

    if DEBUG:
        threading.Thread(
            target=lambda: (time.sleep(2), webbrowser.open("http://127.0.0.1:5000")),
            daemon=True
        ).start()

    app.run(host="0.0.0.0", port=5000, threaded=True, use_reloader=False)