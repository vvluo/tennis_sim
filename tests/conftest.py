"""Put the repository root on sys.path so tests can import both the
`simulation` package and the top-level analysis modules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
