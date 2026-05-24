import time


class StateMachine:
  def __init__(self, behavior=None):
    self.behavior = behavior or {}
    self.current_state = "STARTING"
    self.last_state_time = time.monotonic()
    self.round_dir = int(self.behavior.get("fixed_round_dir", 0))
    self.turns_left = int(self.behavior.get("turns", 12))
    self.time_diff = 0.0
    self.search_for_dir = self.round_dir == 0
    self._round_dir_votes = 0
    self._scheduled_state = None
    self._scheduled_state_block = False
    self._time_last_avoid = -999.0
    self.next_pillar = None
    self.is_pillar_round = bool(self.behavior.get("pillars", False))

    if self.round_dir != 0:
      self.round_dir = 1 if self.round_dir > 0 else -1

  def transition_state(self, new_state):
    self.current_state = new_state
    self.last_state_time = time.monotonic()

  def schedule_state_transition(self, new_state, delay_seconds, block=True):
    self._scheduled_state = (new_state, time.monotonic() + float(delay_seconds))
    self._scheduled_state_block = block

  def add_round_dir_vote(self, vote):
    if not self.search_for_dir or vote == 0:
      return
    self._round_dir_votes += 1 if vote > 0 else -1
    threshold = int(self.behavior.get("round_dir_vote_threshold", 10))
    if abs(self._round_dir_votes) >= threshold:
      self.round_dir = 1 if self._round_dir_votes > 0 else -1
      self.search_for_dir = False
      self.transition_state("PD-CENTER")

  def should_transition_state(self, portion_orange, portion_blue, pillars):
    now = time.monotonic()
    self.time_diff = now - self.last_state_time

    if self._scheduled_state is not None:
      new_state, scheduled_time = self._scheduled_state
      if now >= scheduled_time:
        self.transition_state(new_state)
        self._scheduled_state = None
        return True
      if self._scheduled_state_block:
        return False

    if self.current_state == "STARTING":
      if pillars and self.is_pillar_round:
        next_pillar = pillars[0]
        area = next_pillar.area
        seen_frames = int(getattr(next_pillar, "seen_frames", 1))
        if (
          area > self.behavior.get("pillar_track_area", 190)
          and seen_frames >= self.behavior.get("pillar_track_confirm_frames", 1)
          and not next_pillar.ignore
        ):
          self.next_pillar = next_pillar
          self.transition_state("TRACKING-PILLAR")
          return True
      if self.round_dir != 0 and not self.search_for_dir:
        self.transition_state("PD-CENTER")
        return True
      return False

    if self.current_state == "PD-CENTER" and self.turns_left <= 0 and self._scheduled_state is None:
      self.schedule_state_transition(
        "DONE",
        self.behavior.get("finish_delay_seconds", 3.1),
        False,
      )
      return True

    if (
      self.current_state in ("TURNING-L", "TURNING-R", "PD-CENTER")
      and self.time_diff < self.behavior.get("state_hold_seconds", 0.4)
    ):
      return False

    if pillars and self.is_pillar_round:
      next_pillar = pillars[0]
      area = next_pillar.area
      seen_frames = int(getattr(next_pillar, "seen_frames", 1))
      if self.current_state == "PD-CENTER":
        self.next_pillar = next_pillar
        if (
          area > self.behavior.get("pillar_track_area", 190)
          and seen_frames >= self.behavior.get("pillar_track_confirm_frames", 1)
          and not next_pillar.ignore
        ):
          self.transition_state("TRACKING-PILLAR")
          return True
      elif self.current_state in ("TRACKING-PILLAR", "PD-CENTER"):
        if (
          area > self.behavior.get("pillar_avoid_area", 530)
          and seen_frames >= self.behavior.get("pillar_avoid_confirm_frames", 1)
          and now - self._time_last_avoid > self.behavior.get("pillar_avoid_cooldown_seconds", 1.0)
        ):
          self.transition_state("AVOIDING-R" if next_pillar.color == "RED" else "AVOIDING-G")
          self.next_pillar = None
          return True

    if self.current_state == "TRACKING-PILLAR" and not pillars:
      self.transition_state("PD-CENTER")
      return True

    if self.current_state in ("AVOIDING-R", "AVOIDING-G"):
      if self.time_diff > self.behavior.get("pillar_avoid_seconds", 2.5):
        self.transition_state("PD-CENTER")
        self._time_last_avoid = now
        return True

    if self.current_state in ("TURNING-L", "TURNING-R"):
      if self.time_diff > self.behavior.get("turn_timeout_seconds", 0.85):
        self.transition_state("PD-CENTER")
        return True
      return False

    min_portion = self.behavior.get("line_marker_min_portion", 0.25)
    if portion_blue > min_portion:
      if self.current_state != "TURNING-R" and self.round_dir < 0:
        self.turns_left -= 1
        delay = self.behavior.get(
          "pillar_turn_delay_seconds" if self.is_pillar_round else "turn_delay_seconds",
          0.3 if self.is_pillar_round else 0.7,
        )
        self.schedule_state_transition("TURNING-L", delay)
      else:
        self.transition_state("PD-CENTER")
      return True

    if portion_orange > min_portion:
      if self.current_state != "TURNING-L" and self.round_dir > 0:
        self.turns_left -= 1
        delay = self.behavior.get(
          "pillar_turn_delay_seconds" if self.is_pillar_round else "turn_delay_seconds",
          0.3 if self.is_pillar_round else 0.7,
        )
        self.schedule_state_transition("TURNING-R", delay)
      else:
        self.transition_state("PD-CENTER")
      return True

    return False

  # Backwards-compatible names for older scripts.
  def transitionState(self, new_state):
    return self.transition_state(new_state)

  def scheduleStateTransition(self, new_state, time_diff, block=True):
    return self.schedule_state_transition(new_state, time_diff, block)

  def shouldTransitionState(self, portion_orange, portion_blue, pillars):
    return self.should_transition_state(portion_orange, portion_blue, pillars)
