import os
import sys
import time
import json
import queue
import logging
import threading
import requests
import re
from datetime import datetime

# Constants
LOG_FILE = "camera_monitor.log"
QUEUE_FILE = "queue.json"
ALERT_LOG_FILE = "alert_counts.log"
RESET_INTERVAL = 300  # seconds

# Telegram bot details
TELEGRAM_BOT_TOKEN = '7802711134:AAELuoLMl9mXncmOuAdYjU_Kw4eHKCdYkT8'
# TELEGRAM_CHAT_ID = '-1002425156117' # store chat id
TELEGRAM_CHAT_ID = '1555830976' # test chat id

# Camera Configuration
CAMERA_STREAMS = [
    {
        "name": "Test Camera",
        "url": "http://192.168.1.246/cgi-bin/eventManager.cgi?action=attach&codes=%5BAlarmLocal%2CVideoMotion%5D&heartbeat=5",
        "auth": ("admin", "Admin@123")
    }
]

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global Variables
camera_alerts = {
    camera["name"]: {
        "simple_count": 0,
        "gap_10_sec": 0,
        "gap_30_sec": 0,
        "gap_60_sec": 0,
        "last_alert_time_gap_10_sec": None,
        "last_alert_time_gap_30_sec": None,
        "last_alert_time_gap_60_sec": None
    }
    for camera in CAMERA_STREAMS
}
message_queue = queue.Queue()


# Utility Functions
def load_persistent_queue():
    """Load unsent messages from a persistent queue file."""
    logger.debug("Loading persistent queue.")
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r") as file:
                messages = json.load(file)
                for message in messages:
                    message_queue.put(message)
                logger.info(f"Loaded {len(messages)} messages from persistent queue.")
        except json.JSONDecodeError:
            logger.error("Persistent queue file is corrupt. Starting fresh.")


def save_persistent_queue():
    """Save unsent messages to a persistent queue file."""
    logger.debug("Saving persistent queue.")
    with open(QUEUE_FILE, "w") as file:
        json.dump(list(message_queue.queue), file, indent=4)
    logger.debug("Unsent messages saved to persistent queue.")


def reset_alert_counts():
    """Reset alert counts for all cameras."""
    logger.debug("Resetting alert counts.")
    for camera_name in camera_alerts:
        for key in camera_alerts[camera_name]:
            camera_alerts[camera_name][key] = 0 if "count" in key else None
    logger.info("Alert counts reset for all cameras.")


def log_alert_counts():
    """Log alert counts for all cameras."""
    logger.debug("Logging alert counts.")
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ALERT_LOG_FILE, "a") as file:
        file.write(f"Timestamp: {current_time}\n")
        for camera_name, data in camera_alerts.items():
            file.write(f"{camera_name}: {json.dumps(data, indent=4)}\n")
        file.write("\n")
    logger.info("Alert counts logged.")


def send_telegram_message(message):
    """Send a message to Telegram."""
    logger.debug(f"Sending Telegram message: {message}")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Message sent to Telegram.")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


# Core Functions
def parse_event(buffer, camera_name):
    """Parse and process camera event data."""
    logger.debug(f"Parsing event for camera: {camera_name}")
    match = re.search(r"Code=(.*?);action=(.*?);index=(.*?);data=({.*})", buffer, re.DOTALL)
    if match:
        code, action, _, data = match.groups()
        logger.debug(f"Parsed event data: code={code}, action={action}")
        try:
            event_data = json.loads(data)
            if code == "VideoMotion" and action == "Start":
                message = (
                    f"🚨 Motion Detected at UrMedz galaxy store!\n"
                    f"📅 Time: {event_data.get('LocaleTime', 'Unknown')}\n"
                    f"📍 Camera: {camera_name}\n"
                    f"🤖 Smart Motion: {event_data.get('SmartMotionEnable', 'Unknown')}"
                )
                return message
        except json.JSONDecodeError:
            logger.error("Failed to parse event data.")
    return None


def listen_to_stream(camera):
    """Listen to a camera's event stream."""
    logger.info(f"Starting stream listener for camera: {camera['name']}")
    while True:
        try:
            response = requests.get(
                camera["url"],
                auth=requests.auth.HTTPDigestAuth(*camera["auth"]),
                stream=True,
                timeout=30
            )
            response.raise_for_status()

            buffer = ""
            for line in response.iter_lines():
                if line:
                    line_decoded = line.decode("utf-8")
                    logger.debug(f"Received line: {line_decoded}")
                    buffer += line_decoded + "\n"
                if "--myboundary" in line.decode("utf-8"):
                    message = parse_event(buffer, camera["name"])
                    if message:
                        logger.info(f"Event detected: {message}")
                        message_queue.put(message)
                        save_persistent_queue()
                    buffer = ""
        except requests.RequestException as e:
            logger.error(f"Stream error for {camera['name']}: {e}")
            time.sleep(10)


def process_message_queue():
    """Send messages from the queue."""
    logger.info("Starting message queue processor.")
    while True:
        message = message_queue.get()
        logger.debug(f"Processing message: {message}")
        while not send_telegram_message(message):
            logger.debug("Retrying message send.")
            time.sleep(10)


def periodic_tasks():
    """Perform periodic tasks such as logging and resetting alert counts."""
    logger.info("Starting periodic tasks thread.")
    while True:
        log_alert_counts()
        reset_alert_counts()
        time.sleep(RESET_INTERVAL)


def main():
    """Main entry point of the application."""
    logger.info("Application starting.")
    load_persistent_queue()

    # Start threads
    for camera in CAMERA_STREAMS:
        threading.Thread(target=listen_to_stream, args=(camera,), daemon=True).start()
    threading.Thread(target=process_message_queue, daemon=True).start()
    threading.Thread(target=periodic_tasks, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        save_persistent_queue()
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
