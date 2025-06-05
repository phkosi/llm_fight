"""Logger configuration used across the engine modules."""

import logging
import sys

# Create a logger instance
logger = logging.getLogger("llm_fight_engine")
logger.setLevel(logging.DEBUG)  # Set the default logging level

# Create a handler for console output
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG) # Set level for this handler

# Create a formatter and set it for the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(console_handler)

# Prevent the logger from propagating to the root logger if it's not desired (optional)
# logger.propagate = False

# Example usage (can be removed later):
# if __name__ == '__main__':
#     logger.debug("This is a debug message from logger.py")
#     logger.info("This is an info message from logger.py")
#     logger.warning("This is a warning message from logger.py")
#     logger.error("This is an error message from logger.py")
#     logger.critical("This is a critical message from logger.py") 
