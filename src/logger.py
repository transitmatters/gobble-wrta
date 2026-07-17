import logging


def set_up_logging(name: str):
    logger = logging.getLogger(name)

    # sets up logger to handle stack traces and other multi-line logs in a way that Datadog can parse
    # notably missing JSON formatting, sorry! thank uv for that
    logHandler = logging.StreamHandler()
    logger.addHandler(logHandler)

    return logger
