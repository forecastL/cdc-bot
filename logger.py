import logging
import os
from datetime import datetime

def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    
    # CRITICAL FIX: Return early if already configured
    if logger.handlers:
        return logger  # Already configured, don't add duplicate handlers
    
    logger.setLevel(logging.DEBUG)

    # Ensure logs directory exists with absolute path
    logs_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Generate unique log file name with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = os.path.join(logs_dir, f"cdc_log_{timestamp}.log")

    try:
        # Buffered file handler for better performance
        file_handler = logging.FileHandler(logfile, encoding="utf-8", mode='a', delay=False)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(module)s.%(funcName)s] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
    except PermissionError as e:
        raise RuntimeError(f"Failed to create log file '{logfile}'.") from e

    # Console handler — clean output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)

    # Add both handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger