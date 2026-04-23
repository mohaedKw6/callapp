#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entrypoint shim — runs the full callv2 bot with Fox-app integration."""
import os, sys, threading, runpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

# Run callv2 as __main__ so its bootstrap block executes.
runpy.run_path(os.path.join(HERE, "callv2.py"), run_name="__main__")
