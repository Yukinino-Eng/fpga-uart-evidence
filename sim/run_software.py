"""Run the existing UART software regression from any working directory."""
from pathlib import Path
import subprocess
import sys

project = Path(__file__).resolve().parents[1] / 'src/pynq'
raise SystemExit(subprocess.call([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
                                 '-p', 'test_uart_*.py', '-v'], cwd=str(project)))

