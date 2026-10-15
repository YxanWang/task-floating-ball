"""Launch the desktop app or use add/list/del from the command line."""
import sys

from task_ball.app import main


if __name__ == "__main__":
    sys.exit(main())
