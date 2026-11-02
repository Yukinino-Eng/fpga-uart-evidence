"""Run the existing UART software regression from any working directory."""
from pathlib import Path
import os
import unittest

project = Path(__file__).resolve().parents[1] / 'src/pynq'
os.chdir(str(project))
suite=unittest.TestSuite()
for pattern in ['test_uart_*.py','test_urx2_power_acceptance.py']:
    suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())

