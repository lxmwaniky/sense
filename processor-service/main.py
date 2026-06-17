import os
import base64
import json
import logging
import sys
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from google.cloud import firestore

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

logger = logging.getLogger("processor")

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
COLLECTION_NAME = os.getenv("FIRESTORE_COLLECTION")

if not PROJECT_ID or not COLLECTION_NAME:
    raise RuntimeError("Environment variables GOOGLE_CLOUD_PROJECT and FIRESTORE_COLLECTION must be set.")

app = FastAPI(title="Project S.E.N.S.E. Processor")
db = firestore.Client(project=PROJECT_ID)

@app.post("/pubsub")
async def handle_pubsub_message(request: Request):
    """
    Endpoint for Pub/Sub Push Subscription.
    """
    envelope = await request.json()

    if not envelope or "message" not in envelope:
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub message format")
    
    payload = envelope["message"]

    if "data" not in payload:
        raise HTTPException(status_code=400, detail="No data in Pub/Sub message")
    
    try:
        decoded_data = base64.b64decode(payload["data"]).decode("utf-8")
        tingle_data = json.loads(decoded_data)

        # Write to Firestore
        # Let Firestore auto-generate the document ID
        update_time, doc_ref = db.collection(COLLECTION_NAME).add(tingle_data)

        logger.info(f"SAVED: Document {doc_ref.id} in collection {COLLECTION_NAME}")
        return {"status": "persisted", "document_id": doc_ref.id}
    
    except Exception as e:
        logger.error(f"ERROR processing message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy"}