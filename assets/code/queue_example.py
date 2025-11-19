import threading
import queue
import paho.mqtt.client as mqtt


def on_connect(client, userdata, flags, rc):
    client.subscribe("cache/a/wis2/se-smhi/data/core/weather/surface-based-observations/synop")

def on_message(client, userdata, msg):
    # put newly received messages into the queue
    q.put(msg.payload.decode())

# create a queue to hold messages. Queue operations are thread save
q = queue.Queue()

# create a worker thread to process messages from the queue asynchronously
def worker():
    while True:
        message = q.get()
        print(f"Processing message: {message}")
		# insert code to extract link and download data here
        q.task_done()

# start the worker thread
threading.Thread(target=worker, daemon=True).start()

# create an MQTT client and set the callback functions
client = mqtt.Client()
client.username_pw_set("everyone", "everyone")
client.on_connect = on_connect
client.on_message = on_message

# connect to the MQTT broker and start the loop
client.connect("globalbroker.meteo.fr", 1883, 60)
client.loop_forever()