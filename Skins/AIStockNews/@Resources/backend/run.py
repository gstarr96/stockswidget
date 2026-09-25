"""Entry point used by the Rainmeter skin (``py -B run.py``)."""

import sys
from pathlib import Path

if sys.version_info < (3, 9):  # noqa: UP036 - users may run this with any Python
    print("AI Stock News needs Python 3.9 or newer.")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stocknews.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
