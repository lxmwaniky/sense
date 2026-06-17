import os
import json
import logging
import sys
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import pubsub_v1

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "logger": record.name,
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

# Force root logger to output JSON to stdout
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

logger = logging.getLogger("ingestor")

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
TOPIC_ID = os.getenv("PUB_SUB_TOPIC_ID")

if not PROJECT_ID or not TOPIC_ID:
    raise RuntimeError("Environment variables GOOGLE_CLOUD_PROJECT and PUB_SUB_TOPIC_ID must be set.")

app = FastAPI(title="Project S.E.N.S.E. Ingestor")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

class Tingle(BaseModel):
    lat: float
    lng: float

@app.post("/tingle")
async def receive_tingle(tingle: Tingle):
    try:
        data = json.dumps(tingle.model_dump()).encode("utf-8")
        future = publisher.publish(topic_path, data)
        message_id = future.result()

        logger.info(f"Successfully published tingle to Pub/Sub. Message ID: {message_id}")
        return {"status": "dispatched", "message_id": message_id}
    except Exception as e:
        logger.error(f"Error publishing message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}