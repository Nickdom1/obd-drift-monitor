"""
OBD-II Decode Library

Pure functions for parsing OBD-II Mode 01 and Mode 06 responses.
No I/O—just bytes in, structured data out.

Supports:
- Mode 01: Current powertrain diagnostic data (standard PIDs)
- Mode 06: On-board monitoring test results (monitor IDs and test IDs)

Parsing follows SAE J1979 structure. Parsers return raw values; scaling and
naming for Mode 06 are applied later via the decode table.
"""

from .mode01 import PidValue, parse_mode01
from .mode06 import MonitorResult, parse_mode06

__version__ = "0.1.0"

__all__ = [
    "parse_mode01",
    "parse_mode06",
    "PidValue",
    "MonitorResult",
]
