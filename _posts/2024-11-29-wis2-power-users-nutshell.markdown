---
layout: post
title:  "Power-using WIS2 in a nutshell"
date:   2024-11-29 21:43:53 +0100
categories: wis2
tags: wis2 
---
This post examines how users with high-availability or high-throughput requirements can obtain data from the WMO Information System 2.0 (WIS2). 

**Disclaimer**: I work for WMO in the WIS-team. While the information in this post is well-researched and based on my experience working for WMO, the thoughts and opinions in this post are my own and do not necessarily represent WMO's views. 
For offical guidance on WIS2, visit the [WIS2 web-pages](https://community.wmo.int/en/activity-areas/wis)  

WIS2 is the World Meteorological Organization next generation IoT data-exchange network. WIS2 is based on MQTT and web-storage. 
In WIS2, consumers and producers communicate through a system of interconnected Global Brokers (GB) and Global Caches (GC).
GBs are MQTT brokers on which [notifications of new data](https://github.com/wmo-im/wis2-notification-message) are published using a topic from the WIS2 [topic-hierarchy](https://github.com/wmo-im/wis2-topic-hierarchy/), 
whereas GCs are web-storage components from which users can download data at scale. 

#### a simple WIS2 downloader one-liner

To obtain data from WIS2, a user establishes a MQTT connection to a broker, subscribes to a topic of interest and processes MQTT messages containing WIS2 notifcations. Notification messages, in JSON format, contain basic information which can be used to filter the data, and also include a URL to a GC from which the 
data associated which the notification can be downloaded.

{% highlight json %}
[..]
        "data_id": "dataset/123/data-granule/UANT01_CWAO_200445___15103.bufr4",
        "metadata_id": "urn:wmo:md:ca-eccc-msc:observations.swob",
        "content": {
            "encoding": "utf-8",
            "value": "encoded bytes from the file",
            "size": 457
        }
    },
    "links": [
        {
            "href": "https://example.org/data/4Pubsub/92c557ef-d28e-4713-91af-2e2e7be6f8ab.bufr4",
            "rel": "canonical",
            "type": "application/bufr"
        },
[..]
{% endhighlight %}
*Extract of a notification message, showing data_id and link properties*

This shell one-liner, leveraging only unix tools, exemplifies how to download data from WIS2. _mosquitto_sub_ connects to a global broker and subscribes to surface observations from Sweden.
The output is read by a loop, piped into a _jq_ expression extracting the data URL from the notification which is in turn piped to _wget_ for download.

{% highlight shell %}
mosquitto_sub -h globalbroker.meteo.fr --username everyone -P everyone  -t "cache/a/wis2/se-smhi/data/core/weather/surface-based-observations/synop" |  while read line ; do echo $line | jq -r '.links[0].href' | wget --input-file=-  ; done
{% endhighlight %}

However, this solution is unsuitable for processing a high rate of messages. Since all commands run synchronously as one process, mosquitto_sub, the part responsible
for receiving new messages from the network, is blocked while data is being downloaded by wget. Evenytually the network buffer will be exhausted leading to data-loss.
The solution is also reliant on a single broker, failure of which will lead to failure of receiving data.

The remainder of this post discusses strategies how to reliably connect to WIS2 and to process data at scale.


### decoupling notification reception and processing

A first step in implementing a high-throughput WIS2 processing solution is to de-couple MQTT message inflow (producer) and the downloading of 
the WIS2 notifications contained in the messages (consumer). This is usually done by introducing a queue between producer and consumer and processing
the queue in a separate process or thread. 
The queue servers multiple purposes. 

#### asynchronous processing

First, introducing a queue allows to process messages asynchronously. Since putting an item into a queue can be done equally fast than the arrival
of new messages, the producer can immediately return to accepting new messages from the network. The processing of these messages can be done independently by a different process. 
This is important because downloading data takes significantly longer than receiving a new MQTT message. 
Messages can arrive through MQTT at a rate of 1000/s, whereas downloading even a small amount of data through the internet from a physically remote
GC can take between 100-1000ms. This is because a new network connection is required, the data needs to be transferred through the network and 
the associated data in WIS2 typically is much larger than the notification message. 
Without a queue and and during peak message arrival, downloading the data associated with one message will block the arrival of 100-1000 messages, 
eventually exhausting the network buffer and leading to data loss.
Subject to enough memory, the queue can buffer a temporary higher inflow rate than processing rate.

The following code implements a simple MQTT subscription, queueing of incoming messages in a queue and processing of the queue in a separate thread.

{% highlight python %}
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
{% endhighlight %}

#### parallel processing to increase download throughput  

Second, the queue makes is possible for multiple consumers to process the queue in parallel and thus to increase the overall download througput. 
This makes sense, because the downloading process spends most of its time waiting for network IO, during which another process can exchange data 
through the network.

The following code adds mutlithreading to the previous solution with 5 threads consuming the queue in parallel.

{% highlight python %}
[..]
# start the worker threads
threads = []
for thread_nr in range(5):
    thread = threading.Thread(target=worker, args=(thread_nr,))
    threads.append(thread)
    thread.start()
[..]
# Wait for all threads to finish
for thread in threads:
    thread.join()

{% endhighlight %}

While multithreading is a good approach to deal with client side IO issues, the overall download throughput will still be limited by 
available network bandwith and server side limitations, such as restrictions of number of connections.


A queue based and multithreaded implementation of a WIS2 connection can handle spikes in message inflow, and has good overall throughput 
due to parallel processing. However, it does not offer high-availability, as it is only connected to a single MQTT broker. 

### high-availability and duplication in WIS2

To compensate for the loss of a single GB, WIS2 provides redundant global infrastructure in the form of multiple GB. 
Instead of just connecting to one GB, users with high-availability requirements must connect to at least two GB. 
New WIS2 notifications will then arrive through both MQTT connections, one providing safeguards against the loss of the other.
However, this redundancy comes at the expense of duplicate messages (technically duplicate messages even arrive with a single GB connection
because redundant GC also publish notifications for the same data). 

To avoid processing the same data multiple times, the property "data_id" in the WIS2 notification message can be used. 
The WIS2 technical specifications prescribe that the "data_id" must be unique for at least 24h. This means that a notfication message
with the same data_id published within 24h can be considered a duplicate and discarded.