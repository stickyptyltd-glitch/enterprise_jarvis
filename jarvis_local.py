"""Single-file launcher for the JARVIS business engine.

Kept as the original quick-start entry point; delegates to the packaged
engine (src.agents.core) and interactive console (src.main).
"""

import os
import sys

# Allow running this file directly from the repo root (without installing).
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if not os.getenv("OPENAI_API_KEY"):
    print("\033[91m\u2715 Error: OPENAI_API_KEY environment variable is not set.\033[0m")
    print("\033[93mPlease run: export OPENAI_API_KEY='your-key'\033[0m")
    sys.exit(1)

from src.main import run_interactive  # noqa: E402

if __name__ == "__main__":
    run_interactive()