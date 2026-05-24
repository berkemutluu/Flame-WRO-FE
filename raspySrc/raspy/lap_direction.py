import cv2
import numpy as np


def find_round_dir(black_img):
  if black_img is None or black_img.size == 0:
    return 0

  edges_img = cv2.Canny(black_img, 30, 90, 3)
  if edges_img.size == 0:
    return 0

  edges_img[0, :] = 0
  edges_img[-1, :] = 0
  wall_heights = np.argmax(edges_img, axis=0)
  wall_heights = np.where(wall_heights == 0, edges_img.shape[0] - 1, wall_heights)
  differences = np.diff(wall_heights)

  min_jump = 9
  counter_clockwise = np.sum(differences > min_jump)
  clockwise = np.sum(differences < -min_jump)
  if clockwise == counter_clockwise:
    return 0
  return -1 if clockwise > counter_clockwise else 1
