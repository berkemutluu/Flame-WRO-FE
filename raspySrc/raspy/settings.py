import json
import os
from copy import deepcopy


DEFAULT_CONFIG = {
  "version": 2,
  "filters": {
    "GRAY": 110,
    "WALL_MAX_SAT": 90,
    "WALL_EXCLUDE_COLORS": True,
    "WALL_EXCLUDE_DILATE": 7,
    "REDLO": [0, 100, 80],
    "REDHI": [4, 255, 255],
    "GREENLO": [30, 80, 30],
    "GREENHI": [90, 255, 255],
    "ORANGELO": [7, 20, 10],
    "ORANGEHI": [37, 255, 255],
    "BLUELO": [100, 85, 90],
    "BLUEHI": [130, 255, 255],
    "PINKLO": [158, 160, 100],
    "PINKHI": [170, 255, 255]
  },
  "contours": {
    "minSize": 80.0,
    "pillar_morph_kernel": 5,
    "pillar_min_width": 4,
    "pillar_min_height": 8,
    "pillar_min_fill_ratio": 0.18
  },
  "camera": {
    "frame_width": 640,
    "frame_height": 480,
    "format": "RGB888",
    "crop_height": 258,
    "flip_180": True,
    "awb_enable": False,
    "mtx": [
      [495.44408865, 0.0, 294.45510998],
      [0.0, 504.36905411, 259.77204181],
      [0.0, 0.0, 1.0]
    ],
    "dist": [[-0.64066312, 0.41901729, -0.00366722, 0.01957175, -0.14404429]]
  },
  "roi": {
    "line": {"x": 270, "y": 180, "w": 100, "h": 30},
    "left_wall": {"x": 0, "y": 0, "w": 100, "h": 150},
    "right_wall": {"x": 540, "y": 0, "w": 100, "h": 150}
  },
  "pd": {
    "kp": 4.5,
    "kd": 8.0,
    "target_black_portion": 0.45
  },
  "control": {
    "speed": 100,
    "turn_speed": 100,
    "avoid_speed": 100,
    "done_sleep_seconds": 1.0,
    "max_correction": 1.0,
    "max_steering_offset": 55,
    "steering_sign": -1,
    "drive_sign": 1,
    "servo_center_deg": 90,
    "servo_min_deg": 15,
    "servo_max_deg": 165
  },
  "behavior": {
    "pillars": False,
    "turns": 12,
    "fixed_round_dir": 0,
    "round_dir_vote_threshold": 10,
    "line_marker_min_portion": 0.25,
    "turn_delay_seconds": 0.7,
    "pillar_turn_delay_seconds": 0.3,
    "turn_timeout_seconds": 0.85,
    "state_hold_seconds": 0.4,
    "finish_delay_seconds": 3.1,
    "pillar_track_area": 190,
    "pillar_avoid_area": 530,
    "pillar_avoid_cooldown_seconds": 1.0,
    "pillar_avoid_seconds": 2.5,
    "pillar_first_phase_seconds": 0.95,
    "pillar_red_first_correction": 0.95,
    "pillar_red_second_correction": -0.72,
    "pillar_green_first_correction": -0.95,
    "pillar_green_second_correction": 0.72,
    "pillar_wall_guard": True,
    "pillar_wall_guard_threshold": 0.62,
    "pillar_wall_guard_correction": 1.0,
    "pillar_area_ema_alpha": 0.35,
    "pillar_lost_hold_frames": 3,
    "pillar_match_max_dx": 90,
    "pillar_track_confirm_frames": 2,
    "pillar_avoid_confirm_frames": 2
  },
  "serial": {
    "enabled": True,
    "port": "/dev/ttyACM0",
    "auto_detect": True,
    "baud_rate": 9600,
    "ready_timeout_seconds": 6.0,
    "write_timeout_seconds": 1.0,
    "send_interval_seconds": 0.02,
    "keepalive_interval_seconds": 0.15
  },
  "web": {
    "enabled": True,
    "host": "0.0.0.0",
    "port": 5000
  },
  "decision_log": {
    "enabled": True,
    "path": "decision_log.jsonl",
    "cycle_interval_seconds": 0.25
  },
  "debug": {
    "log_every_seconds": 0.5,
    "preview_masks": True,
    "sample_radius": 4,
    "sample_hue_margin": 8,
    "sample_sv_margin": 35,
    "sample_gray_margin": 18,
    "save_frames": False,
    "frame_dir": "debug_frames",
    "frame_every_seconds": 1.0
  }
}


class ConfigLoader:
  def __init__(self, file_path):
    self.file_path = file_path
    self.config = deepcopy(DEFAULT_CONFIG)
    self.load_config()

  def load_config(self):
    if not os.path.exists(self.file_path):
      return
    with open(self.file_path, "r", encoding="utf-8") as file:
      loaded = json.load(file)
    if not isinstance(loaded, dict):
      raise ValueError("config root must be an object")
    self.config = merge_dicts(deepcopy(DEFAULT_CONFIG), loaded)
    self._apply_legacy_keys(loaded)

  def _apply_legacy_keys(self, loaded):
    if "ArduinoSerialPort" in loaded and not loaded.get("serial", {}).get("port"):
      self.config["serial"]["port"] = loaded["ArduinoSerialPort"]
    if "PD" in loaded:
      pd = loaded["PD"]
      if "kp" in pd:
        self.config["pd"]["kp"] = pd["kp"]
      if "kd" in pd:
        self.config["pd"]["kd"] = pd["kd"]
    if "ROI" in loaded and isinstance(loaded["ROI"], dict):
      self.config["roi"] = merge_dicts(self.config["roi"], loaded["ROI"])

  def get_property(self, key, default=None):
    return self.config.get(key, default)

  def get_path(self, path, default=None):
    current = self.config
    for part in str(path).split("."):
      if not isinstance(current, dict) or part not in current:
        return default
      current = current[part]
    return current

  def set_path(self, path, value):
    parts = str(path).split(".")
    current = self.config
    for part in parts[:-1]:
      if part not in current or not isinstance(current[part], dict):
        current[part] = {}
      current = current[part]
    current[parts[-1]] = value

  def save_config(self, path=None):
    target = path or self.file_path
    with open(target, "w", encoding="utf-8") as file:
      json.dump(self.config, file, indent=2)
      file.write("\n")


def merge_dicts(base, overrides):
  for key, value in overrides.items():
    if isinstance(value, dict) and isinstance(base.get(key), dict):
      base[key] = merge_dicts(base[key], value)
    else:
      base[key] = value
  return base


def parse_override_value(text):
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    lowered = text.lower()
    if lowered == "true":
      return True
    if lowered == "false":
      return False
    if lowered == "null":
      return None
    return text
