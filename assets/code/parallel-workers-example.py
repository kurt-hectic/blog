import threading
import queue
import paho.mqtt.client as mqtt


def on_connect(client, userdata, flags, rc, properties=None):
    client.subscribe("cache/a/wis2/se-smhi/data/core/weather/surface-based-observations/synop")
    
def on_message(client, userdata, msg):
    # put newly received messages into the queue
    q.put(msg.payload.decode())

# create a queue to hold messages. Queue operations are thread save
q = queue.Queue()

# create a worker thread to process messages from the queue asynchronously
def worker():
    print("creating worker")
    while True:
        message = q.get()
        print(f"Processing message: {message}")
		# insert code to extract link and download data here
        q.task_done()

# start the worker threads
threads = []
for thread_nr in range(5):
    thread = threading.Thread(target=worker, args=(thread_nr,))
    threads.append(thread)
    thread.start()

# create an MQTT client and set the callback functions
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set("everyone", "everyone")
client.on_connect = on_connect
client.on_message = on_message

# connect to the MQTT broker and start the loop
client.connect("globalbroker.meteo.fr", 1883, 60)
client.loop_start()

# Wait for all threads to finish
for thread in threads:
    thread.join()
