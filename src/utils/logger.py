"""
Logging configuration for the arbitrage bot
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.logging import RichHandler

# Rich console for formatted output
console = Console()

# Global logger instance
bot_logger = None


def setup_logging(level: str = "INFO", environment: str = "development"):
    """
    Setup logging configuration with rich formatting

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        environment: Environment name (development, production)
    """
    global bot_logger

    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Configure logging level
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Create logger
    bot_logger = logging.getLogger("arbitrage_bot")
    bot_logger.setLevel(log_level)

    # Clear existing handlers
    bot_logger.handlers.clear()

    # Console handler with Rich formatting
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=environment == "development"
    )
    console_handler.setLevel(log_level)

    # File handler for persistent logs
    log_file = log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file

    # Format for file logs
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)

    # Add handlers
    bot_logger.addHandler(console_handler)
    bot_logger.addHandler(file_handler)

    # Separate file for trade logs
    trade_log_file = log_dir / f"trades_{datetime.now().strftime('%Y%m%d')}.log"
    trade_handler = logging.FileHandler(trade_log_file)
    trade_handler.setLevel(logging.INFO)
    trade_handler.setFormatter(file_formatter)

    # Filter to only log messages with extra={'trade': True}
    class TradeFilter(logging.Filter):
        def filter(self, record):
            return hasattr(record, 'trade') and record.trade

    trade_handler.addFilter(TradeFilter())
    bot_logger.addHandler(trade_handler)

    # Prevent propagation to root logger
    bot_logger.propagate = False

    bot_logger.info(f"Logging initialized - Level: {level}, Environment: {environment}")

    return bot_logger


# Initialize with default settings if imported directly
if bot_logger is None:
    bot_logger = setup_logging()
