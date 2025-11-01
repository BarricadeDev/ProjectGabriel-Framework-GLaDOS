"""
This is now a compatibility wrapper around the new tools package.
For new development, import directly from tools package.
"""

# Import everything from the new tools package for backward compatibility
from tools import *

# Preserve the original interface
from tools.memory import memory_system, MemorySystem
from tools import get_all_tools, handle_function_call
