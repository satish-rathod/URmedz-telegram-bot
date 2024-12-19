import requests
import threading
import queue
import logging
import sys
import time
import json
import re
import os

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('camera_monitor.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# List of camera streams
CAMERA_STREAMS = [
    {"name": "FMCG wall", "url": "http://192.168.1.202/cgi-bin/eventManager.cgi?action=attach&codes=%5BAlarmLocal%2CVideoMotion%5D&heartbeat=5", "auth": ("admin", "Admin@123")},
    {"name": "outdoor entrence", "url": "http://192.168.1.205/cgi-bin/eventManager.cgi?action=attach&codes=%5BAlarmLocal%2CVideoMotion%5D&heartbeat=5", "auth": ("admin", "Admin@123")}
]

# Telegram bot details
TELEGRAM_BOT_TOKEN = '7802711134:AAELuoLMl9mXncmOuAdYjU_Kw4eHKCdYkT8'
TELEGRAM_CHAT_ID = '-1002425156117'

# Persistent queue file
QUEUE_FILE = "queue.json"

# Message queue
message_queue = queue.Queue()

def load_persistent_queue():
    """Load messages from the persistent queue file into the in-memory queue."""
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, 'r') as file:
            try:
                messages = json.load(file)
                for message in messages:
                    message_queue.put(message)
                logger.info(f"Loaded {len(messages)} unsent messages from {QUEUE_FILE}")
            except json.JSONDecodeError:
                logger.error("Failed to load persistent queue file. Starting fresh queue.")
    else:
        logger.info("No persistent queue file found. Starting with an empty queue.")

def save_persistent_queue():
    """Save the in-memory queue to the persistent queue file."""
    messages = list(message_queue.queue)  # Convert the queue to a list
    with open(QUEUE_FILE, 'w') as file:
        json.dump(messages, file, indent=4)
    logger.debug("Persistent queue saved to disk.")

def send_telegram_message(message):
    """Send a message to Telegram via bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Message sent to Telegram successfully")
            return True  # Indicate success
        else:
            logger.error(f"Failed to send message to Telegram: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error sending message to Telegram: {e}")
    return False  # Indicate failure

def process_queue():
    """Process messages from the queue and retry on failure."""
    logger.debug("Queue processing thread started")
    while True:
        message = message_queue.get()
        if message:
            logger.info(f"Processing message: {message}")
            while True:  # Keep retrying until the message is successfully sent
                if send_telegram_message(message):
                    break  # Exit retry loop on success
                logger.warning("Retrying to send message in 60 seconds...")
                time.sleep(60)  # Wait before retrying
            save_persistent_queue()  # Update the queue file after sending a message
            message_queue.task_done()

def parse_multipart_event(buffer: str, camera_name: str):
    """Parse a single multipart event from the buffer."""
    logger.debug(f"Parsing buffer: {buffer}")
    event_match = re.search(r'Code=(.*?);action=(.*?);index=(.*?);data=({.*})', buffer, re.DOTALL)
    if event_match:
        code, action, index, data_str = event_match.groups()
        try:
            data = json.loads(data_str)
            if code == "VideoMotion" and action == "Start":
                message = f"""
🚨 Motion Detected at urmedz galaxy store!

📅 Local Time: {data.get('LocaleTime', 'Unknown')}
📍 Name: {camera_name}
🤖 Smart Motion Enabled: {data.get('SmartMotionEnable', 'Unknown')}
"""
                return message
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON data: {data_str}")
    return None

def listen_to_event_stream(camera):
    """Listen to a camera's event stream."""
    while True:
        try:
            logger.info(f"Connecting to {camera['name']} event stream...")
            response = requests.get(
                camera["url"], 
                auth=requests.auth.HTTPDigestAuth(*camera["auth"]), 
                stream=True,
                timeout=30
            )

            logger.debug(f"Response status code: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"Failed to connect to {camera['name']}. Status Code: {response.status_code}")
                time.sleep(10)
                continue

            logger.info(f"Connected to {camera['name']} event stream")
            multipart_buffer = ""

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8', errors='replace')
                    logger.debug(f"Received line: {decoded_line}")
                    multipart_buffer += decoded_line + '\n'

                    if '--myboundary' in decoded_line:
                        logger.debug("Boundary detected in stream")
                        message = parse_multipart_event(multipart_buffer, camera['name'])
                        if message:
                            logger.info(f"Motion detected by {camera['name']}")
                            message_queue.put(message)
                            save_persistent_queue()  # Save queue after adding a new message
                        multipart_buffer = ""  # Reset buffer

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error with {camera['name']}: {e}")
            if not is_camera_connected(camera):
                send_telegram_message(f"{camera['name']} camera is offline")
            time.sleep(10)
        except Exception as e:
            logger.error(f"Unexpected error in {camera['name']} stream: {e}")
            time.sleep(10)

def is_camera_connected(camera):
    """Check if the camera connection has been successfully established."""
    try:
        response = requests.get(
            camera["url"], 
            auth=requests.auth.HTTPDigestAuth(*camera["auth"]), 
            timeout=10
        )
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def main():
    """Main function to initialize and start monitoring."""
    logger.debug("Starting main function")
    load_persistent_queue()  # Load any pending messages
    threading.Thread(target=process_queue, daemon=True).start()

    for camera in CAMERA_STREAMS:
        logger.debug(f"Starting thread for {camera['name']}")
        t = threading.Thread(target=listen_to_event_stream, args=(camera,), daemon=True)
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        save_persistent_queue()  # Save the queue before shutting down
        logger.info("Monitoring stopped by user")

if __name__ == "__main__":
    logger.debug("Program started")
    main()
