import logging
from http.server import HTTPServer

from .config import parse_args
from .db import MediaDB
from .handler import MediaRequestHandler


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[37m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    ACCESS_COLOR = "\033[90m"
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        if record.name == "access":
            color = self.ACCESS_COLOR
        timestamp = self.formatTime(record, self.datefmt)
        level = f"{record.levelname:<8}"
        prefix = f"{color}[{timestamp}] {level} {record.name}:{self.RESET} "
        message = record.getMessage()
        return f"{prefix}{message}"


def main():
    config = parse_args()
    handler = logging.StreamHandler()
    formatter = ColorFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    root.setLevel(level)
    MediaRequestHandler.config = config
    MediaRequestHandler.db = MediaDB(config.db_path)

    server = HTTPServer((config.host, config.port), MediaRequestHandler)
    logging.info("Media server listening on %s:%s", config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
