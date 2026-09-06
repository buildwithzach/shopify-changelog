#!/usr/bin/env python3
"""Run the installer bundled with the skill."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent /
                       "shopify-changelog/scripts/setup.py"), run_name="__main__")
