#!/usr/bin/env python3
"""
Entry point for the DJI media management server.
Keep this file thin to match the project layout.
"""

import os
import sys

if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from media_server.app import main


if __name__ == "__main__":
    main()
