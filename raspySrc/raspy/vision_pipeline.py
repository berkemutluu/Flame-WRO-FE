import cv2
import numpy as np

from settings import ConfigLoader
from vision_types import Pillar

class Pipeline:
  def __init__(self, configloader: ConfigLoader):
    self.configloader = configloader

  def undistort(self, image: np.ndarray):
    mtx, dist = np.array(self.configloader.get_property("camera")['mtx']), np.array(self.configloader.get_property("camera")['dist'])
    return cv2.undistort(image, mtx, dist, None, mtx)

  def crop(self, image: np.ndarray):
    crop_height = int(self.configloader.get_property("camera")['crop_height'])
    return image[crop_height:,:]

  @staticmethod
  def hsv_range_mask(hsv: np.ndarray, lower, upper):
    lower = tuple(lower)
    upper = tuple(upper)
    if lower[0] <= upper[0]:
      return cv2.inRange(hsv, lower, upper)

    low_wrap = (0, lower[1], lower[2])
    high_wrap = upper
    low_direct = lower
    high_direct = (179, upper[1], upper[2])
    return cv2.bitwise_or(
      cv2.inRange(hsv, low_direct, high_direct),
      cv2.inRange(hsv, low_wrap, high_wrap),
    )

  def filter_RG_Bl(self, hsv: np.ndarray, color_image: np.ndarray):
    """
    Extracts red/green pillars and the dark wall mask.
    """
    filters = self.configloader.get_property("filters")
    redMin = tuple(filters['REDLO'])
    redMax = tuple(filters['REDHI'])
    greenMin = tuple(filters['GREENLO'])
    greenMax = tuple(filters['GREENHI'])
    orangeMin = tuple(filters['ORANGELO'])
    orangeMax = tuple(filters['ORANGEHI'])
    blueMin = tuple(filters['BLUELO'])
    blueMax = tuple(filters['BLUEHI'])
    pinkMin = tuple(filters['PINKLO'])
    pinkMax = tuple(filters['PINKHI'])
    grayThresh = int(filters['GRAY'])
    wallMaxSat = int(filters.get('WALL_MAX_SAT', 90))
    excludeColors = bool(filters.get('WALL_EXCLUDE_COLORS', True))
    excludeDilate = int(filters.get('WALL_EXCLUDE_DILATE', 7))

    rMask = self.hsv_range_mask(hsv, redMin, redMax)
    gMask = self.hsv_range_mask(hsv, greenMin, greenMax)
    oMask = self.hsv_range_mask(hsv, orangeMin, orangeMax)
    bMask = self.hsv_range_mask(hsv, blueMin, blueMax)
    pMask = self.hsv_range_mask(hsv, pinkMin, pinkMax)

    blurredR = cv2.medianBlur(rMask, 5)
    blurredG = cv2.medianBlur(gMask, 5)
    grayImage = cv2.cvtColor(color_image, cv2.COLOR_BGR2GRAY)
    blurredImg = cv2.GaussianBlur(grayImage, (3, 3), 0)
    darkMask = cv2.inRange(blurredImg, 0, grayThresh)
    lowSatMask = cv2.inRange(hsv[:, :, 1], 0, wallMaxSat)
    blackimg = cv2.bitwise_and(darkMask, lowSatMask)

    if excludeColors:
      colorMask = cv2.bitwise_or(rMask, gMask)
      colorMask = cv2.bitwise_or(colorMask, oMask)
      colorMask = cv2.bitwise_or(colorMask, bMask)
      colorMask = cv2.bitwise_or(colorMask, pMask)
      if excludeDilate > 0:
        kernelSize = excludeDilate if excludeDilate % 2 == 1 else excludeDilate + 1
        kernel = np.ones((kernelSize, kernelSize), np.uint8)
        colorMask = cv2.dilate(colorMask, kernel)
      blackimg = cv2.bitwise_and(blackimg, cv2.bitwise_not(colorMask))

    blackimg = cv2.medianBlur(blackimg, 3)
    return {"green": blurredG, "red": blurredR, "black": blackimg}


  def filter_OB(self, hsv: np.ndarray):
    """
    Extracts the orange and blue colors from the image -> this is used to detect the turn markers
    """
    orangeMin = tuple(self.configloader.get_property("filters")['ORANGELO'])
    orangeMax = tuple(self.configloader.get_property("filters")['ORANGEHI'])
    blueMin = tuple(self.configloader.get_property("filters")['BLUELO'])
    blueMax = tuple(self.configloader.get_property("filters")['BLUEHI'])
    oMask = self.hsv_range_mask(hsv, orangeMin, orangeMax)
    bMask = self.hsv_range_mask(hsv, blueMin, blueMax)
    # blur images to remove noise
    blurredO = cv2.medianBlur(oMask, 5)
    blurredB = cv2.medianBlur(bMask, 5)
    # return [blurredO, blurredB]
    return {"orange": blurredO, "blue": blurredB}
  
  def filter_parking(self, hsv: np.ndarray):
    pinkMin = tuple(self.configloader.get_property("filters")['PINKLO'])
    pinkMax = tuple(self.configloader.get_property("filters")['PINKHI'])
    pMask = cv2.inRange(hsv, pinkMin, pinkMax)
    blurredP = cv2.medianBlur(pMask, 5)
    return blurredP

  def get_pillars(self, imgIn: np.ndarray, type = "RED") -> list[Pillar]:
    """
      Extracts pillars from filtered image
    """
    contours_config = self.configloader.get_property("contours")
    minSize = float(contours_config['minSize'])
    minWidth = int(contours_config.get("pillar_min_width", 4))
    minHeight = int(contours_config.get("pillar_min_height", 8))
    minFillRatio = float(contours_config.get("pillar_min_fill_ratio", 0.18))
    kernelSize = int(contours_config.get("pillar_morph_kernel", 5))

    mask = cv2.medianBlur(imgIn, 5)
    if kernelSize > 1:
      kernelSize = kernelSize if kernelSize % 2 == 1 else kernelSize + 1
      kernel = np.ones((kernelSize, kernelSize), np.uint8)
      mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
      mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    processedContours = []
    for contour in contours:
      size = cv2.contourArea(contour)
      if size > minSize:
        rx, ry, w, h = cv2.boundingRect(contour)
        width = int(w)
        height = int(h)
        bboxArea = max(1, width * height)
        fillRatio = float(size) / float(bboxArea)

        if width < minWidth or height < minHeight or fillRatio < minFillRatio:
          continue

        x = int(rx + width / 2)
        processedContours.append(Pillar(x, width, height, type, ry, size))
    return processedContours
