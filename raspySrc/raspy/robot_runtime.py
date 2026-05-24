import argparse
import glob
import json
import os
import threading
import time

import cv2
import numpy as np

from control_panel import RobotWebServer
from decision_log import DecisionLogger
from drive_state import StateMachine
from lap_direction import find_round_dir
from settings import ConfigLoader, parse_override_value
from vision_pipeline import Pipeline
from vision_types import Pillar, extract_ROI


def clamp(value, low, high):
  return max(low, min(high, value))


def rect_roi(image, rect):
  h, w = image.shape[:2]
  x = int(clamp(rect.get("x", 0), 0, max(0, w - 1)))
  y = int(clamp(rect.get("y", 0), 0, max(0, h - 1)))
  rw = int(max(1, rect.get("w", w)))
  rh = int(max(1, rect.get("h", h)))
  return extract_ROI(image, [x, y], [min(w, x + rw), min(h, y + rh)])


def portion(mask):
  if mask is None or mask.size == 0:
    return 0.0
  return cv2.countNonZero(mask) / float(mask.shape[0] * mask.shape[1])


def steering_offset_to_servo_angle(offset, control):
  center = int(control.get("servo_center_deg", 90))
  min_angle = int(control.get("servo_min_deg", 15))
  max_angle = int(control.get("servo_max_deg", 165))
  if min_angle > max_angle:
    min_angle, max_angle = max_angle, min_angle
  offset = int(round(offset))
  offset_limit = min(center - min_angle, max_angle - center)
  offset = int(clamp(offset, -offset_limit, offset_limit))
  return int(clamp(center + offset, min_angle, max_angle))


def pillar_snapshot(pillar):
  if pillar is None:
    return None
  return {
    "color": pillar.color,
    "x": int(pillar.screen_x),
    "y": int(pillar.y),
    "width": int(pillar.width),
    "height": int(pillar.height),
    "area": int(pillar.area),
    "raw_area": int(pillar.raw_area),
    "contour_area": round(float(pillar.contour_area), 1),
    "seen_frames": int(pillar.seen_frames),
    "held": bool(pillar.held),
    "ignored": bool(pillar.ignore),
  }


def detect_serial_port(config):
  configured = str(config.get("port", "/dev/ttyACM0"))
  if not config.get("auto_detect", True):
    return configured
  for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
    matches = sorted(glob.glob(pattern))
    if matches:
      return matches[0]
  try:
    import serial.tools.list_ports
    ports = sorted(port.device for port in serial.tools.list_ports.comports())
    if ports:
      return ports[0]
  except Exception:
    pass
  return configured


class ArduinoLink:
  def __init__(self, serial_config, dry_run=False):
    self.config = serial_config
    self.dry_run = dry_run or not bool(serial_config.get("enabled", True))
    self.ser = None
    self.last_command = {}
    self.last_command_at = {}
    self.port = detect_serial_port(serial_config)

  def connect(self):
    if self.dry_run:
      print("Serial disabled; running without Arduino output.")
      return
    try:
      import serial
    except ImportError:
      print("pyserial is not installed; running without Arduino output.")
      self.dry_run = True
      return

    self.ser = serial.Serial(
      self.port,
      int(self.config.get("baud_rate", 9600)),
      timeout=0.2,
      write_timeout=float(self.config.get("write_timeout_seconds", 1.0)),
    )
    try:
      self.ser.reset_input_buffer()
    except Exception:
      pass
    ready = self.wait_ready(float(self.config.get("ready_timeout_seconds", 6.0)))
    print(f"Arduino {'ready' if ready else 'connected'} on {self.port}")

  def wait_ready(self, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while self.ser and time.monotonic() < deadline:
      line = self.ser.readline().decode("ascii", errors="ignore").strip()
      if line == "READY":
        return True
    return False

  def send(self, command, value=None, force=False):
    if value is None:
      text = command
      key = command
    else:
      text = f"{command}:{int(value)}"
      key = command

    now = time.monotonic()
    send_interval = float(self.config.get("send_interval_seconds", 0.02))
    keepalive_interval = float(self.config.get("keepalive_interval_seconds", 0.15))
    last_at = self.last_command_at.get(key, 0.0)
    if not force and self.last_command.get(key) == text and now - last_at < keepalive_interval:
      return
    if not force and self.last_command.get(key) != text and now - last_at < send_interval:
      return

    if self.dry_run:
      self.last_command[key] = text
      self.last_command_at[key] = now
      return
    if not self.ser:
      return
    self.ser.write((text + "\n").encode("ascii"))
    self.ser.flush()
    self.last_command[key] = text
    self.last_command_at[key] = now
    self.drain_input()

  def drain_input(self):
    if not self.ser:
      return
    try:
      while self.ser.in_waiting:
        self.ser.read(self.ser.in_waiting)
    except Exception:
      pass

  def apply(self, servo_angle, drive_speed):
    self.send("STEER", servo_angle)
    self.send("DRIVE", drive_speed)

  def stop(self):
    self.send("STOP", force=True)

  def close(self):
    try:
      self.stop()
    finally:
      if self.ser and self.ser.is_open:
        self.ser.close()


class PiCamera:
  def __init__(self, camera_config):
    self.config = camera_config
    self.picam2 = None

  def start(self):
    try:
      from picamera2 import Picamera2
    except ImportError as exc:
      raise RuntimeError("Picamera2 is not installed. Run this on the Raspberry Pi camera environment.") from exc

    self.picam2 = Picamera2()
    size = (
      int(self.config.get("frame_width", 640)),
      int(self.config.get("frame_height", 480)),
    )
    fmt = self.config.get("format", "RGB888")
    self.picam2.configure(self.picam2.create_preview_configuration(main={"size": size, "format": fmt}))
    self.picam2.start()
    try:
      self.picam2.set_controls({"AwbEnable": bool(self.config.get("awb_enable", False))})
    except Exception:
      pass

  def capture_bgr(self):
    frame = self.picam2.capture_array()
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    if self.config.get("flip_180", True):
      frame = cv2.rotate(frame, cv2.ROTATE_180)
    return frame

  def stop(self):
    if self.picam2:
      self.picam2.stop()


class RobotRunner:
  def __init__(self, configloader, no_serial=False):
    self.configloader = configloader
    self.config = configloader.config
    self.pipeline = Pipeline(configloader)
    self.sm = StateMachine(self.config["behavior"])
    self.last_error = 0.0
    self.last_log = 0.0
    self.last_frame_save = 0.0
    self.latest_jpeg = None
    self.latest_sample_image = None
    self.latest_status = {}
    self.closest_pillar = None
    self._pillar_track = None
    self.manual_until = 0.0
    self.manual_servo_angle = None
    self.manual_drive_speed = None
    self._lock = threading.RLock()
    self.arduino = ArduinoLink(self.config["serial"], dry_run=no_serial)
    self.camera = PiCamera(self.config["camera"])
    self.decision_logger = DecisionLogger.from_config(self.config, configloader.file_path)

  def start(self):
    self.arduino.connect()
    self.camera.start()
    self.decision_logger.record_decision(
      "runtime_start",
      inputs={
        "config_path": self.configloader.file_path,
        "serial_enabled": bool(self.config["serial"].get("enabled", True)),
        "web_enabled": bool(self.config["web"].get("enabled", True)),
      },
      selected={
        "serial_port": self.arduino.port,
        "initial_state": self.sm.current_state,
        "round_dir": self.sm.round_dir,
        "pillars_enabled": self.sm.is_pillar_round,
      },
      force=True,
    )

  def stop(self):
    try:
      self.arduino.close()
      self.camera.stop()
    finally:
      self.decision_logger.close()

  def cycle(self):
    color_image = self.pipeline.crop(self.camera.capture_bgr())
    hsv_image = cv2.cvtColor(color_image, cv2.COLOR_BGR2HSV)
    preview = color_image.copy()
    with self._lock:
      self.latest_sample_image = color_image.copy()

    line_roi = rect_roi(hsv_image, self.config["roi"]["line"])
    orange_blue = self.pipeline.filter_OB(line_roi)
    full_orange_blue = self.pipeline.filter_OB(hsv_image)
    portion_orange = portion(orange_blue["orange"])
    portion_blue = portion(orange_blue["blue"])

    rgbl = self.pipeline.filter_RG_Bl(hsv_image, color_image)
    left_wall = rect_roi(rgbl["black"], self.config["roi"]["left_wall"])
    right_wall = rect_roi(rgbl["black"], self.config["roi"]["right_wall"])
    portion_black_l = portion(left_wall)
    portion_black_r = portion(right_wall)

    pillars = self.detect_pillars(hsv_image, rgbl)
    state_before = self.state_snapshot()
    transitioned = self.sm.should_transition_state(portion_orange, portion_blue, pillars)
    round_vote = 0
    if self.sm.search_for_dir:
      round_votes_before = self.sm._round_dir_votes
      round_vote = find_round_dir(rgbl["black"])
      self.sm.add_round_dir_vote(round_vote)
      if round_vote != 0 and not self.sm.search_for_dir:
        self.decision_logger.record_decision(
          "round_direction_selected",
          inputs={
            "last_vote": round_vote,
            "vote_sum_before": round_votes_before,
            "vote_threshold": int(self.config["behavior"].get("round_dir_vote_threshold", 10)),
          },
          selected={"round_dir": self.sm.round_dir},
          reasoning={"vote_sum": self.sm._round_dir_votes},
          force=True,
        )
    state_after = self.state_snapshot()
    if transitioned or state_after != state_before:
      self.decision_logger.record_decision(
        "state_update",
        inputs={
          "state_before": state_before,
          "line_orange": round(float(portion_orange), 4),
          "line_blue": round(float(portion_blue), 4),
          "pillar_count": len(pillars),
          "closest_pillar": pillar_snapshot(pillars[0] if pillars else None),
          "round_vote": round_vote,
        },
        selected=state_after,
        reasoning={
          "transitioned": bool(transitioned),
          "state_time_seconds": round(float(self.sm.time_diff), 3),
          "is_pillar_round": bool(self.sm.is_pillar_round),
        },
        force=True,
      )

    previous_error = self.last_error
    correction, error = self.compute_correction(pillars, portion_black_l, portion_black_r)
    self.last_error = error

    control = self.config["control"]
    max_correction = float(control.get("max_correction", 1.0))
    correction = clamp(correction, -max_correction, max_correction)
    steering_offset = correction * float(control.get("max_steering_offset", 55)) * int(control.get("steering_sign", -1))
    servo_angle = steering_offset_to_servo_angle(steering_offset, control)
    speed = self.speed_for_state()

    if self.sm.current_state == "DONE":
      servo_angle = steering_offset_to_servo_angle(0, control)
      speed = 0

    drive_speed = int(speed * int(control.get("drive_sign", 1)))
    manual_active = False
    with self._lock:
      manual_active = time.monotonic() < self.manual_until
      if manual_active:
        if self.manual_servo_angle is not None:
          servo_angle = self.manual_servo_angle
        if self.manual_drive_speed is not None:
          drive_speed = self.manual_drive_speed
    self.arduino.apply(servo_angle, drive_speed)
    self.decision_logger.record_decision(
      "drive_output",
      inputs={
        "state": self.sm.current_state,
        "round_dir": self.sm.round_dir,
        "turns_left": self.sm.turns_left,
        "wall_left": round(float(portion_black_l), 4),
        "wall_right": round(float(portion_black_r), 4),
        "line_orange": round(float(portion_orange), 4),
        "line_blue": round(float(portion_blue), 4),
        "pillar_count": len(pillars),
        "closest_pillar": pillar_snapshot(pillars[0] if pillars else None),
      },
      selected={
        "servo_angle": int(servo_angle),
        "drive_speed": int(drive_speed),
        "correction": round(float(correction), 4),
      },
      reasoning={
        "error": round(float(error), 4),
        "previous_error": round(float(previous_error), 4),
        "kp": float(self.config["pd"].get("kp", 4.5)),
        "kd": float(self.config["pd"].get("kd", 8.0)),
        "max_correction": float(max_correction),
        "manual_override": bool(manual_active),
      },
      sampled=True,
    )
    self.update_preview(
      preview,
      rgbl,
      full_orange_blue,
      pillars,
      servo_angle,
      drive_speed,
      correction,
      portion_black_l,
      portion_black_r,
      portion_orange,
      portion_blue,
    )
    self.update_status(servo_angle, drive_speed, correction, portion_black_l, portion_black_r, portion_orange, portion_blue, len(pillars))
    self.log_status(servo_angle, drive_speed, correction, portion_black_l, portion_black_r, portion_orange, portion_blue, len(pillars))
    self.save_debug_frame(color_image)

    return self.sm.current_state != "DONE"

  def state_snapshot(self):
    scheduled = self.sm._scheduled_state[0] if self.sm._scheduled_state else None
    return {
      "state": self.sm.current_state,
      "round_dir": self.sm.round_dir,
      "turns_left": self.sm.turns_left,
      "search_for_dir": bool(self.sm.search_for_dir),
      "scheduled_state": scheduled,
    }

  def detect_pillars(self, hsv_image, rgbl):
    pillars = self.pipeline.get_pillars(rgbl["red"], "RED") + self.pipeline.get_pillars(rgbl["green"], "GREEN")
    pillars.sort(key=lambda p: p.raw_area, reverse=True)
    if pillars:
      next_pillar = pillars[0]
      check_width = max(next_pillar.width, 12)
      x1 = int(next_pillar.screen_x - check_width * 0.5)
      x2 = int(next_pillar.screen_x + check_width * 0.5)
      pillar_roi = extract_ROI(hsv_image, [max(0, x1), 0], [min(hsv_image.shape[1], x2), hsv_image.shape[0]])
      if pillar_roi.size:
        masks = self.pipeline.filter_OB(pillar_roi)
        if portion(masks["orange"]) > 0.00005 or portion(masks["blue"]) > 0.00005:
          next_pillar.ignore = True
    pillars = self.stabilize_pillars(pillars)
    return pillars

  def stabilize_pillars(self, pillars):
    behavior = self.config["behavior"]
    alpha = float(clamp(float(behavior.get("pillar_area_ema_alpha", 0.35)), 0.0, 1.0))
    hold_frames = int(max(0, behavior.get("pillar_lost_hold_frames", 3)))
    match_dx = float(max(0.0, behavior.get("pillar_match_max_dx", 90)))

    if not pillars:
      if self._pillar_track and self._pillar_track["missing"] < hold_frames:
        self._pillar_track["missing"] += 1
        held = Pillar(
          self._pillar_track["x"],
          self._pillar_track["width"],
          self._pillar_track["height"],
          self._pillar_track["color"],
          self._pillar_track["y"],
          self._pillar_track.get("contour_area", 0.0),
        )
        held.stable_area = self._pillar_track["stable_area"]
        held.seen_frames = self._pillar_track["seen_frames"]
        held.ignore = self._pillar_track.get("ignore", False)
        held.held = True
        self.closest_pillar = held
        return [held]
      self._pillar_track = None
      self.closest_pillar = None
      return []

    closest = pillars[0]
    raw_area = closest.raw_area
    matched = (
      self._pillar_track is not None
      and self._pillar_track["color"] == closest.color
      and abs(self._pillar_track["x"] - closest.screen_x) <= match_dx
    )
    if matched:
      stable_area = self._pillar_track["stable_area"] * (1.0 - alpha) + raw_area * alpha
      seen_frames = self._pillar_track["seen_frames"] + 1
    else:
      stable_area = float(raw_area)
      seen_frames = 1

    closest.stable_area = stable_area
    closest.seen_frames = seen_frames
    self._pillar_track = {
      "x": closest.screen_x,
      "width": closest.width,
      "height": closest.height,
      "y": closest.y,
      "color": closest.color,
      "stable_area": stable_area,
      "seen_frames": seen_frames,
      "missing": 0,
      "ignore": closest.ignore,
      "contour_area": closest.contour_area,
    }
    pillars.sort(key=lambda p: p.area, reverse=True)
    self.closest_pillar = closest
    return pillars

  def compute_correction(self, pillars, portion_black_l, portion_black_r):
    state = self.sm.current_state
    pd = self.config["pd"]
    behavior = self.config["behavior"]
    error = 0.0
    correction = 0.0

    if state == "TRACKING-PILLAR" and pillars:
      frame_width = int(self.config["camera"].get("frame_width", 640))
      error = (pillars[0].screen_x - frame_width / 2.0) / frame_width
    elif state in ("PD-CENTER", "PD-RIGHT", "PD-LEFT"):
      target = float(pd.get("target_black_portion", 0.45))
      if self.sm.round_dir < 0:
        error = target - portion_black_r
      elif self.sm.round_dir > 0:
        error = portion_black_l - target

    correction = error * float(pd.get("kp", 4.5)) + (error - self.last_error) * float(pd.get("kd", 8.0))

    if state == "TURNING-L":
      correction = -1.0
    elif state == "TURNING-R":
      correction = 1.0
    elif state == "AVOIDING-R":
      correction = self.pillar_avoid_correction(
        behavior.get("pillar_red_first_correction", 0.95),
        behavior.get("pillar_red_second_correction", -0.72),
        portion_black_l,
        portion_black_r,
      )
    elif state == "AVOIDING-G":
      correction = self.pillar_avoid_correction(
        behavior.get("pillar_green_first_correction", -0.95),
        behavior.get("pillar_green_second_correction", 0.72),
        portion_black_l,
        portion_black_r,
      )
    elif state in ("STARTING", "DONE"):
      correction = 0.0

    return correction, error

  def pillar_avoid_correction(self, first_correction, second_correction, portion_black_l, portion_black_r):
    behavior = self.config["behavior"]
    phase_correction = (
      float(first_correction)
      if self.sm.time_diff < float(behavior.get("pillar_first_phase_seconds", 0.95))
      else float(second_correction)
    )

    if not behavior.get("pillar_wall_guard", True):
      return phase_correction

    threshold = float(behavior.get("pillar_wall_guard_threshold", 0.62))
    guard = float(behavior.get("pillar_wall_guard_correction", 1.0))
    if portion_black_l > threshold and portion_black_l > portion_black_r:
      return guard
    if portion_black_r > threshold and portion_black_r > portion_black_l:
      return -guard
    return phase_correction

  def speed_for_state(self):
    control = self.config["control"]
    state = self.sm.current_state
    if state in ("TURNING-L", "TURNING-R"):
      return int(control.get("turn_speed", control.get("speed", 100)))
    if state in ("AVOIDING-R", "AVOIDING-G", "TRACKING-PILLAR"):
      return int(control.get("avoid_speed", control.get("speed", 100)))
    if state == "DONE":
      return 0
    return int(control.get("speed", 100))

  def update_status(self, servo_angle, drive_speed, correction, black_l, black_r, orange, blue, pillar_count):
    with self._lock:
      self.latest_status = {
        "state": self.sm.current_state,
        "round_dir": self.sm.round_dir,
        "turns_left": self.sm.turns_left,
        "servo_angle": int(servo_angle),
        "drive_speed": int(drive_speed),
        "correction": round(float(correction), 3),
        "wall_left": round(float(black_l), 3),
        "wall_right": round(float(black_r), 3),
        "orange": round(float(orange), 3),
        "blue": round(float(blue), 3),
        "pillars": int(pillar_count),
        "serial_port": self.arduino.port,
      }
      if self.sm.current_state in ("AVOIDING-R", "AVOIDING-G"):
        first_phase = float(self.config["behavior"].get("pillar_first_phase_seconds", 0.95))
        self.latest_status["avoid_phase"] = "first" if self.sm.time_diff < first_phase else "second"
      if self.closest_pillar:
        self.latest_status.update({
          "closest_pillar_color": self.closest_pillar.color,
          "closest_pillar_area": int(self.closest_pillar.area),
          "closest_pillar_raw_area": int(self.closest_pillar.raw_area),
          "closest_pillar_x": int(self.closest_pillar.screen_x),
          "closest_pillar_seen": int(self.closest_pillar.seen_frames),
          "closest_pillar_held": bool(self.closest_pillar.held),
        })

  def status_snapshot(self):
    with self._lock:
      return dict(self.latest_status)

  def update_preview(self, image, rgbl, orange_blue, pillars, servo_angle, drive_speed, correction, black_l, black_r, orange, blue):
    self.draw_preview_overlay(image, rgbl, orange_blue, pillars, servo_angle, drive_speed, correction, black_l, black_r, orange, blue)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    if ok:
      with self._lock:
        self.latest_jpeg = encoded.tobytes()

  def preview_jpeg(self):
    with self._lock:
      return self.latest_jpeg

  def sample_color(self, x, y, radius=4):
    with self._lock:
      if self.latest_sample_image is None:
        raise ValueError("no camera frame available yet")
      image = self.latest_sample_image.copy()

    h, w = image.shape[:2]
    x = int(clamp(int(round(float(x))), 0, w - 1))
    y = int(clamp(int(round(float(y))), 0, h - 1))
    radius = int(clamp(int(radius), 0, 30))
    x1 = max(0, x - radius)
    x2 = min(w, x + radius + 1)
    y1 = max(0, y - radius)
    y2 = min(h, y + radius + 1)
    patch = image[y1:y2, x1:x2]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).reshape(-1)
    bgr = patch.reshape(-1, 3)
    median_hsv = np.median(hsv, axis=0).round().astype(int)
    low_hsv = np.percentile(hsv, 10, axis=0).round().astype(int)
    high_hsv = np.percentile(hsv, 90, axis=0).round().astype(int)
    median_gray = int(round(float(np.median(gray))))
    low_gray = int(round(float(np.percentile(gray, 10))))
    high_gray = int(round(float(np.percentile(gray, 90))))
    median_bgr = np.median(bgr, axis=0).round().astype(int)
    rgb = [int(median_bgr[2]), int(median_bgr[1]), int(median_bgr[0])]
    return {
      "x": x,
      "y": y,
      "radius": radius,
      "image_width": int(w),
      "image_height": int(h),
      "hsv": [int(v) for v in median_hsv],
      "hsv_low": [int(v) for v in low_hsv],
      "hsv_high": [int(v) for v in high_hsv],
      "gray": median_gray,
      "gray_low": low_gray,
      "gray_high": high_gray,
      "rgb": rgb,
      "hex": "#{:02x}{:02x}{:02x}".format(*rgb),
    }

  def filter_bounds_from_sample(self, sample, hue_margin, sv_margin):
    return self.filter_bounds_from_samples([sample], hue_margin, sv_margin)

  def filter_bounds_from_samples(self, samples, hue_margin, sv_margin):
    hue_margin = int(clamp(int(hue_margin), 0, 60))
    sv_margin = int(clamp(int(sv_margin), 0, 160))
    samples = [self.normalize_sample(sample) for sample in samples]
    if not samples:
      raise ValueError("at least one sample is required")

    hues = sorted(int(sample["hsv"][0]) % 180 for sample in samples)
    if len(hues) == 1:
      start_h = end_h = hues[0]
    else:
      largest_gap = -1
      largest_gap_index = 0
      for index, hue in enumerate(hues):
        next_hue = hues[(index + 1) % len(hues)]
        if index == len(hues) - 1:
          next_hue += 180
        gap = next_hue - hue
        if gap > largest_gap:
          largest_gap = gap
          largest_gap_index = index
      start_h = hues[(largest_gap_index + 1) % len(hues)]
      end_h = hues[largest_gap_index]

    hue_span = (end_h - start_h) % 180
    if hue_span + hue_margin * 2 >= 179:
      lo_h = 0
      hi_h = 179
    else:
      lo_h = (start_h - hue_margin) % 180
      hi_h = (end_h + hue_margin) % 180

    s_low = min(sample["hsv_low"][1] for sample in samples)
    v_low = min(sample["hsv_low"][2] for sample in samples)
    s_high = max(sample["hsv_high"][1] for sample in samples)
    v_high = max(sample["hsv_high"][2] for sample in samples)
    return (
      [
        int(clamp(lo_h, 0, 179)),
        int(clamp(s_low - sv_margin, 0, 255)),
        int(clamp(v_low - sv_margin, 0, 255)),
      ],
      [
        int(clamp(hi_h, 0, 179)),
        int(clamp(s_high + sv_margin, 0, 255)),
        int(clamp(v_high + sv_margin, 0, 255)),
      ],
    )

  def gray_threshold_from_samples(self, samples, gray_margin):
    gray_margin = int(clamp(int(gray_margin), 0, 120))
    samples = [self.normalize_sample(sample) for sample in samples]
    if not samples:
      raise ValueError("at least one sample is required")
    gray_high = max(sample["gray_high"] for sample in samples)
    return int(clamp(gray_high + gray_margin, 0, 255))

  def wall_saturation_from_samples(self, samples, sat_margin):
    sat_margin = int(clamp(int(sat_margin), 0, 160))
    samples = [self.normalize_sample(sample) for sample in samples]
    if not samples:
      raise ValueError("at least one sample is required")
    sat_high = max(sample["hsv_high"][1] for sample in samples)
    return int(clamp(sat_high + sat_margin, 0, 255))

  def normalize_sample(self, sample):
    if not isinstance(sample, dict):
      raise ValueError("sample must be an object")

    def hsv_triplet(key):
      values = sample.get(key)
      if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError(f"sample.{key} must be an HSV triplet")
      return [
        int(clamp(int(values[0]), 0, 179)),
        int(clamp(int(values[1]), 0, 255)),
        int(clamp(int(values[2]), 0, 255)),
      ]

    hsv = hsv_triplet("hsv")
    hsv_low = hsv_triplet("hsv_low")
    hsv_high = hsv_triplet("hsv_high")
    gray_value = int(clamp(int(sample.get("gray", hsv[2])), 0, 255))
    gray_low = int(clamp(int(sample.get("gray_low", gray_value)), 0, 255))
    gray_high = int(clamp(int(sample.get("gray_high", gray_value)), 0, 255))
    return {
      "hsv": hsv,
      "hsv_low": hsv_low,
      "hsv_high": hsv_high,
      "gray": gray_value,
      "gray_low": gray_low,
      "gray_high": gray_high,
    }

  def sample_settings(self, radius=None, hue_margin=None, sv_margin=None, gray_margin=None):
    debug = self.config["debug"]
    return (
      debug.get("sample_radius", 4) if radius is None else radius,
      debug.get("sample_hue_margin", 8) if hue_margin is None else hue_margin,
      debug.get("sample_sv_margin", 35) if sv_margin is None else sv_margin,
      debug.get("sample_gray_margin", 18) if gray_margin is None else gray_margin,
    )

  def apply_color_sample(self, target, action, x, y, radius=None, hue_margin=None, sv_margin=None, gray_margin=None):
    radius, hue_margin, sv_margin, gray_margin = self.sample_settings(radius, hue_margin, sv_margin, gray_margin)
    target = str(target or "").upper()
    if target not in ("RED", "GREEN", "ORANGE", "BLUE", "PINK", "WALL", "BLACK"):
      raise ValueError("target must be RED, GREEN, ORANGE, BLUE, PINK, or WALL")
    action = str(action or "range").lower()
    sample = self.sample_color(x, y, radius)
    if target in ("WALL", "BLACK"):
      gray = self.gray_threshold_from_samples([sample], gray_margin)
      wall_sat = self.wall_saturation_from_samples([sample], sv_margin)
      with self._lock:
        self.configloader.set_path("filters.GRAY", gray)
        self.configloader.set_path("filters.WALL_MAX_SAT", wall_sat)
        self.config = self.configloader.config
      return {
        "sample": sample,
        "target": "WALL",
        "action": "gray",
        "gray": gray,
        "wall_max_sat": wall_sat,
        "filters": self.config["filters"],
      }

    lo, hi = self.filter_bounds_from_sample(sample, hue_margin, sv_margin)
    with self._lock:
      if action in ("lo", "low"):
        self.configloader.set_path(f"filters.{target}LO", lo)
      elif action in ("hi", "high"):
        self.configloader.set_path(f"filters.{target}HI", hi)
      elif action in ("range", "both"):
        self.configloader.set_path(f"filters.{target}LO", lo)
        self.configloader.set_path(f"filters.{target}HI", hi)
      else:
        raise ValueError("action must be range, lo, or hi")
      self.config = self.configloader.config
      actual_lo = self.config["filters"][f"{target}LO"]
      actual_hi = self.config["filters"][f"{target}HI"]
    return {
      "sample": sample,
      "target": target,
      "action": action,
      "lo": actual_lo,
      "hi": actual_hi,
      "filters": self.config["filters"],
    }

  def apply_color_samples(self, target, samples, hue_margin=None, sv_margin=None, gray_margin=None):
    _, hue_margin, sv_margin, gray_margin = self.sample_settings(None, hue_margin, sv_margin, gray_margin)
    target = str(target or "").upper()
    if target not in ("RED", "GREEN", "ORANGE", "BLUE", "PINK", "WALL", "BLACK"):
      raise ValueError("target must be RED, GREEN, ORANGE, BLUE, PINK, or WALL")
    if not isinstance(samples, list) or not samples:
      raise ValueError("samples must be a non-empty list")
    samples = [self.normalize_sample(sample) for sample in samples[:32]]

    with self._lock:
      if target in ("WALL", "BLACK"):
        gray = self.gray_threshold_from_samples(samples, gray_margin)
        wall_sat = self.wall_saturation_from_samples(samples, sv_margin)
        self.configloader.set_path("filters.GRAY", gray)
        self.configloader.set_path("filters.WALL_MAX_SAT", wall_sat)
        self.config = self.configloader.config
        return {
          "samples": samples,
          "target": "WALL",
          "action": "gray",
          "gray": gray,
          "wall_max_sat": wall_sat,
          "filters": self.config["filters"],
        }

      lo, hi = self.filter_bounds_from_samples(samples, hue_margin, sv_margin)
      self.configloader.set_path(f"filters.{target}LO", lo)
      self.configloader.set_path(f"filters.{target}HI", hi)
      self.config = self.configloader.config
      return {
        "samples": samples,
        "target": target,
        "action": "samples",
        "lo": lo,
        "hi": hi,
        "filters": self.config["filters"],
      }

  def tint_mask(self, image, mask, color, alpha=0.45):
    if mask is None or mask.shape[:2] != image.shape[:2]:
      return
    pixels = mask > 0
    if not np.any(pixels):
      return
    tint = np.zeros_like(image)
    tint[:, :] = color
    blended = cv2.addWeighted(image, 1.0 - alpha, tint, alpha, 0)
    image[pixels] = blended[pixels]

  def draw_preview_overlay(self, image, rgbl, orange_blue, pillars, servo_angle, drive_speed, correction, black_l, black_r, orange, blue):
    if self.config["debug"].get("preview_masks", True):
      self.tint_mask(image, rgbl.get("black"), (255, 210, 60), 0.38)
      self.tint_mask(image, rgbl.get("red"), (40, 40, 255), 0.52)
      self.tint_mask(image, rgbl.get("green"), (40, 230, 60), 0.52)
      self.tint_mask(image, orange_blue.get("orange"), (0, 150, 255), 0.52)
      self.tint_mask(image, orange_blue.get("blue"), (255, 120, 20), 0.52)

    for color, key in (((0, 255, 255), "line"), ((255, 220, 0), "left_wall"), ((255, 220, 0), "right_wall")):
      rect = self.config["roi"].get(key, {})
      x, y = int(rect.get("x", 0)), int(rect.get("y", 0))
      w, h = int(rect.get("w", 0)), int(rect.get("h", 0))
      cv2.rectangle(image, (x, y), (x + w, y + h), color, 2)
      cv2.putText(image, key, (x + 4, max(14, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    for pillar in pillars:
      x, y, w, h = pillar.rect
      color = (0, 0, 255) if pillar.color == "RED" else (0, 255, 0)
      cv2.rectangle(image, (x, y), (x + w, y + h), color, 2)
      label = f"{pillar.color.lower()} area={pillar.area}"
      if pillar.stable_area is not None and abs(pillar.area - pillar.raw_area) > 20:
        label += f" raw={pillar.raw_area}"
      if pillar.held:
        label += " held"
      if pillar.ignore:
        label += " ignored"
      cv2.putText(image, label, (x, max(14, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    pillar_count = len(pillars)
    if self.closest_pillar:
      closest_text = (
        f"closest {self.closest_pillar.color} area={self.closest_pillar.area} "
        f"raw={self.closest_pillar.raw_area} seen={self.closest_pillar.seen_frames}"
      )
    else:
      closest_text = "closest pillar area=0"
    lines = [
      f"{self.sm.current_state} dir={self.sm.round_dir} turns={self.sm.turns_left}",
      f"servo={servo_angle} speed={drive_speed} corr={correction:.2f}",
      f"walls L={black_l:.2f} R={black_r:.2f} line O={orange:.2f} B={blue:.2f} pillars={pillar_count}",
      closest_text,
    ]
    y = 22
    for text in lines:
      cv2.putText(image, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 3, cv2.LINE_AA)
      cv2.putText(image, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 255, 230), 1, cv2.LINE_AA)
      y += 24

  def update_config(self, path, value):
    with self._lock:
      self.configloader.set_path(path, value)
      self.config = self.configloader.config
      self.arduino.config = self.config["serial"]
      self.camera.config = self.config["camera"]
      self.sm.behavior = self.config["behavior"]
      self.sm.is_pillar_round = bool(self.config["behavior"].get("pillars", False))
    self.decision_logger.record_decision(
      "config_update",
      inputs={"path": path, "value": value},
      selected={"path": path},
      force=True,
    )

  def manual_command(self, command, value=None):
    command = str(command or "").upper()
    with self._lock:
      self.manual_until = time.monotonic() + 1.0
      if command == "STOP":
        self.manual_servo_angle = steering_offset_to_servo_angle(0, self.config["control"])
        self.manual_drive_speed = 0
        self.arduino.stop()
      elif command == "STEER":
        if value is None:
          raise ValueError("value is required")
        self.manual_servo_angle = int(value)
        self.arduino.send(command, int(value), force=True)
      elif command == "DRIVE":
        if value is None:
          raise ValueError("value is required")
        self.manual_drive_speed = int(value)
        self.arduino.send(command, int(value), force=True)
      else:
        raise ValueError(f"unknown command: {command}")
      self.decision_logger.record_decision(
        "manual_command",
        inputs={"command": command, "value": value},
        selected={
          "manual_servo_angle": self.manual_servo_angle,
          "manual_drive_speed": self.manual_drive_speed,
        },
        reasoning={"override_seconds": 1.0},
        force=True,
      )

  def log_status(self, servo_angle, drive_speed, correction, black_l, black_r, orange, blue, pillar_count):
    now = time.monotonic()
    every = float(self.config["debug"].get("log_every_seconds", 0.5))
    if every <= 0 or now - self.last_log < every:
      return
    self.last_log = now
    print(
      f"state={self.sm.current_state} dir={self.sm.round_dir} turns_left={self.sm.turns_left} "
      f"servo={servo_angle} speed={drive_speed} corr={correction:.2f} "
      f"wallL={black_l:.2f} wallR={black_r:.2f} orange={orange:.2f} blue={blue:.2f} pillars={pillar_count}"
    )

  def save_debug_frame(self, image):
    debug = self.config["debug"]
    if not debug.get("save_frames", False):
      return
    now = time.monotonic()
    if now - self.last_frame_save < float(debug.get("frame_every_seconds", 1.0)):
      return
    self.last_frame_save = now
    frame_dir = os.path.abspath(debug.get("frame_dir", "debug_frames"))
    os.makedirs(frame_dir, exist_ok=True)
    cv2.imwrite(os.path.join(frame_dir, "latest.jpg"), image)


def build_parser():
  default_config = os.path.join(os.path.dirname(__file__), "settings.json")
  parser = argparse.ArgumentParser(description="Headless WRO Future Engineers robot runner.")
  parser.add_argument("--config", default=default_config, help="Path to config JSON.")
  parser.add_argument("--set", action="append", default=[], metavar="PATH=VALUE", help="Override config, e.g. --set control.speed=90")
  parser.add_argument("--save-config", action="store_true", help="Save config after applying overrides.")
  parser.add_argument("--print-config", action="store_true", help="Print effective config and exit.")
  parser.add_argument("--no-serial", action="store_true", help="Run without sending Arduino commands.")
  parser.add_argument("--pillars", action="store_true", help="Enable pillar round behavior.")
  parser.add_argument("--no-pillars", action="store_true", help="Disable pillar round behavior.")
  parser.add_argument("--fixed-dir", type=int, choices=(-1, 0, 1), help="-1 clockwise vote, 1 counter-clockwise vote, 0 auto.")
  parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames; 0 means run forever.")
  parser.add_argument("--log-every", type=float, help="Seconds between status lines.")
  parser.add_argument("--web", action="store_true", help="Start preview/config webpage.")
  parser.add_argument("--no-web", action="store_true", help="Disable preview/config webpage.")
  parser.add_argument("--host", help="Webpage host bind address.")
  parser.add_argument("--port", type=int, help="Webpage port.")
  return parser


def apply_cli_overrides(configloader, args):
  if args.pillars:
    configloader.set_path("behavior.pillars", True)
  if args.no_pillars:
    configloader.set_path("behavior.pillars", False)
  if args.fixed_dir is not None:
    configloader.set_path("behavior.fixed_round_dir", args.fixed_dir)
  if args.log_every is not None:
    configloader.set_path("debug.log_every_seconds", args.log_every)
  if args.web:
    configloader.set_path("web.enabled", True)
  if args.no_web:
    configloader.set_path("web.enabled", False)
  if args.host:
    configloader.set_path("web.host", args.host)
  if args.port is not None:
    configloader.set_path("web.port", args.port)
  for item in args.set:
    if "=" not in item:
      raise ValueError(f"invalid --set override: {item}")
    key, value = item.split("=", 1)
    configloader.set_path(key, parse_override_value(value))


def main(argv=None):
  args = build_parser().parse_args(argv)
  configloader = ConfigLoader(args.config)
  apply_cli_overrides(configloader, args)
  if args.save_config:
    configloader.save_config()
  if args.print_config:
    print(json.dumps(configloader.config, indent=2))
    return 0

  runner = RobotRunner(configloader, no_serial=args.no_serial)
  web_server = None
  frame_count = 0
  try:
    runner.start()
    if configloader.get_path("web.enabled", True):
      web_server = RobotWebServer(
        runner,
        configloader.get_path("web.host", "0.0.0.0"),
        configloader.get_path("web.port", 5000),
      )
      web_server.start()
    while True:
      keep_running = runner.cycle()
      frame_count += 1
      if args.max_frames and frame_count >= args.max_frames:
        break
      if not keep_running:
        time.sleep(float(configloader.get_path("control.done_sleep_seconds", 1.0)))
        break
  except KeyboardInterrupt:
    print("Interrupted; stopping robot.")
  except Exception as exc:
    print(f"Robot runtime error: {exc}")
    runner.decision_logger.record_decision(
      "runtime_error",
      selected={"message": str(exc)},
      force=True,
    )
    return 1
  finally:
    if web_server:
      web_server.stop()
    runner.stop()
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
