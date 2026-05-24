import json
import math
import os
import time


class DecisionLogger:
  def __init__(self, path, enabled=True, cycle_interval_seconds=0.25):
    self.enabled = bool(enabled)
    self.path = os.path.abspath(path)
    self.cycle_interval_seconds = max(0.0, float(cycle_interval_seconds))
    self._last_sampled_at = 0.0
    self._file = None

    if self.enabled:
      directory = os.path.dirname(self.path)
      if directory:
        os.makedirs(directory, exist_ok=True)
      self._file = open(self.path, "w", encoding="utf-8")
      self.record_decision(
        "session_start",
        selected={"log_file": self.path},
        reasoning={"mode": "replace"},
        force=True,
      )

  @classmethod
  def from_config(cls, config, config_path):
    log_config = config.get("decision_log", {})
    path = log_config.get("path", "decision_log.jsonl")
    if not os.path.isabs(path):
      path = os.path.join(os.path.dirname(os.path.abspath(config_path)), path)
    return cls(
      path,
      log_config.get("enabled", True),
      log_config.get("cycle_interval_seconds", 0.25),
    )

  def record_decision(self, name, inputs=None, selected=None, reasoning=None, sampled=False, force=False):
    if not self.enabled or self._file is None:
      return

    now = time.monotonic()
    if sampled and not force:
      if self.cycle_interval_seconds > 0 and now - self._last_sampled_at < self.cycle_interval_seconds:
        return
      self._last_sampled_at = now

    entry = {
      "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
      "monotonic_seconds": round(now, 3),
      "decision": name,
    }
    if inputs is not None:
      entry["inputs"] = self._safe_json(inputs)
    if selected is not None:
      entry["selected"] = self._safe_json(selected)
    if reasoning is not None:
      entry["reasoning"] = self._safe_json(reasoning)

    json.dump(entry, self._file, separators=(",", ":"), allow_nan=False)
    self._file.write("\n")
    self._file.flush()

  def close(self):
    if self._file is None:
      return
    self.record_decision("session_stop", force=True)
    self._file.close()
    self._file = None

  def _safe_json(self, value):
    if value is None or isinstance(value, (str, bool)):
      return value
    if isinstance(value, int):
      return value
    if isinstance(value, float):
      return value if math.isfinite(value) else None
    if isinstance(value, dict):
      return {str(key): self._safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
      return [self._safe_json(item) for item in value]
    if hasattr(value, "item"):
      return self._safe_json(value.item())
    return str(value)
