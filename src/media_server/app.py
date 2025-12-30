import logging
from http.server import HTTPServer

from .config import parse_args
from .db import MediaDB
from .handler import MediaRequestHandler


def main():
    config = parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
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
