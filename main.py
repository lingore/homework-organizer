#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动器：等价于 python -m homework_organizer，方便不熟悉 -m 用法的同学。

用法：
    python main.py scan    ./作业 --ext .pdf .docx
    python main.py rename  ./作业 --fields 3,1
    python main.py archive ./作业 --by semester
    python main.py report  ./作业
    python main.py undo    ./作业
"""
import sys

from homework_organizer.cli import main

if __name__ == "__main__":
    sys.exit(main())
