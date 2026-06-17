import time
import sys
from google.cloud import pubsub_v1

def initialize_emulator():
    print("Waiting for Pub/Sub Emulator to warm up...")
    time.sleep(5)
    
    publisher = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()
    
    topic_path = publisher.topic_path("sense-project", "emergency-beacons")
    sub_path = subscriber.subscription_path("sense-project", "processor-push")
    
    # Create topic
    try:
        publisher.create_topic(name=topic_path)
        print("Created Pub/Sub topic: emergency-beacons")
    except Exception as e:
        print("Pub/Sub Topic might already exist or log:", e)
        
    # Create push subscription
    try:
        subscriber.create_subscription(
            name=sub_path,
            topic=topic_path,
            push_config=pubsub_v1.types.PushConfig(
                push_endpoint="http://processor-service:8081/pubsub"
            )
        )
        print("Created Push Subscription pointing to processor-service")
    except Exception as e:
        print("Pub/Sub Subscription might already exist or log:", e)

if __name__ == "__main__":
    initialize_emulator()
