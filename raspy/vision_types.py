import numpy as np


class Pillar:
  ignore = False
  big_correction = False
  def __init__(self, screen_x: int, width: int, height: int, color: str, y: int = 0, contour_area: float = 0.0):
    self.screen_x = screen_x
    self.width = width
    self.height = height
    self.color = color
    self.y = y
    self.contour_area = float(contour_area)
    self.stable_area = None
    self.seen_frames = 1
    self.held = False

  @property
  def x(self):
    return int(self.screen_x - self.width / 2)

  @property
  def rect(self):
    return (self.x, self.y, self.width, self.height)

  @property
  def raw_area(self):
    return int(self.width * self.height)

  @property
  def area(self):
    if self.stable_area is not None:
      return int(round(self.stable_area))
    return self.raw_area


def extract_ROI(image: np.ndarray, startxy: list, endxy: list) -> np.ndarray:
  """
  Extracts the ROIs from the image
  """
  
  return image[startxy[1]:endxy[1], startxy[0]:endxy[0]]
