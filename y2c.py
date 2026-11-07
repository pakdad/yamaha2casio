#!/usr/bin/env python3
"""y2c -- Yamaha style -> Casio CT-X5000 rhythm converter (command line).

The commands live in `y2c/cli.py`; this is only the thing you type.  They
moved there so that `y2c_gui.py` can import them: a top-level `y2c.py` beside
a `y2c/` package is unimportable, because the package wins the name, and a
frozen build has no script on disk to load by path either.  One entry point
for both front ends also means the window and the terminal cannot drift.
"""
import sys

from y2c.cli import main

if __name__ == "__main__":
    sys.exit(main())
