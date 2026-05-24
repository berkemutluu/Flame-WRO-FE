import sys
from pathlib import Path


ONBOARD_DIR = Path(__file__).resolve().parent / "onboard"
sys.path.insert(0, str(ONBOARD_DIR))

from robot_runtime import main  # noqa: E402


if __name__ == "__main__":
  raise SystemExit(main())
