import threading
import queue
import json
import time
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta


def on_connect(client, userdata, flags, rc, properties=None):
    client.subscribe("cache/a/wis2/se-smhi/data/core/weather/surface-based-observations/synop")
    
def on_message(client, userdata, msg):
    print("Message received from client:", client._client_id.decode())
    try:
        notification = json.loads(msg.payload.decode())
        data_id = notification["properties"]["data_id"]

        # queue message only if data_id has not been already processed in the last 24 hours
        if not data_id in processed_dataids or datetime.now() - processed_dataids[data_id] > timedelta(days=1):
            processed_dataids[data_id] = datetime.now()
            q.put(notification)

    except Exception as e:
        print("Error processing message:", e)

# create a queue to hold messages. Queue operations are thread save
q = queue.Queue()
# dictionary to track processed data IDs
processed_dataids = {}

# create a worker thread to process messages from the queue asynchronously
def worker():
    print("creating worker")
    while True:
        message = q.get()
        print(f"Processing message: {message}")
		# insert code to extract link and download data here
        q.task_done()

# start the worker thread
threading.Thread(target=worker, daemon=True).start()

# create MQTT clients and set the callback functions
for gb in ["globalbroker.meteo.fr", "gb.wis.cma.cn"]:

    print("Connecting to broker:", gb)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=f"client_{gb}")
    client.username_pw_set("everyone", "everyone")
    client.on_connect = on_connect
    client.on_message = on_message

    # connect to the MQTT broker and start the loop
    client.connect(gb, 1883, 60)
    client.loop_start()
    
# avoid exiting to process messages    
while True:
    time.sleep(10)
