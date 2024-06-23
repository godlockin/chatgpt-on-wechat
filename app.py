import logging
import os
import signal
import sys
import threading
import time

import config
from channel import channel_factory
from common import const
from config import (
    load_config,
    config,
)
from plugins import PluginManager

logger = logging.getLogger('itchat')


def sigterm_handler(signum, frame):
    logger.info(f"Signal {signum} received, exiting...")
    config.save_user_datas()
    sys.exit(0)


def start_channel(channel_name: str):
    channel = channel_factory.create_channel(channel_name)
    if channel_name in const.PLUGIN_CHANNELS:
        PluginManager().load_plugins()

    if config.get("use_linkai"):
        try:
            from common import linkai_client
            threading.Thread(target=linkai_client.start, args=(channel,)).start()
        except Exception as e:
            logger.error(f"Failed to start linkai_client: {e}")

    channel.startup()


def run():
    try:
        load_config()
        signal.signal(signal.SIGINT, sigterm_handler)
        signal.signal(signal.SIGTERM, sigterm_handler)

        channel_name = config.get("channel_type", "wx")
        if "--cmd" in sys.argv:
            channel_name = "terminal"

        if channel_name == "wxy":
            os.environ["WECHATY_LOG"] = "warn"

        start_channel(channel_name)

        while True:
            time.sleep(1)

    except Exception as e:
        logger.error("App startup failed!")
        logger.exception(e)


if __name__ == "__main__":
    run()
