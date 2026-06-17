import os
import base64
import json
import logging
import sys
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import firestore
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from tenacity import retry, stop_after_attempt, wait_exponential

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
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

if not PROJECT_ID or not COLLECTION_NAME:
    raise RuntimeError("Environment variables GOOGLE_CLOUD_PROJECT and FIRESTORE_COLLECTION must be set.")

db = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    db = firestore.Client(project=PROJECT_ID)
    yield
    if hasattr(db, 'close'):
        db.close()
    logger.info("Shutting down Firestore client...")

app = FastAPI(title="Project S.E.N.S.E. Processor", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

# --- OpenTelemetry GCP Trace Setup ---
try:
    tracer_provider = TracerProvider()
    trace.set_tracer_provider(tracer_provider)
    cloud_trace_exporter = CloudTraceSpanExporter(project_id=PROJECT_ID)
    tracer_provider.add_span_processor(BatchSpanProcessor(cloud_trace_exporter))
    FastAPIInstrumentor.instrument_app(app)
    logger.info("OpenTelemetry Tracing initialized with Cloud Trace Exporter")
except Exception as e:
    logger.warning(f"Could not initialize Tracing (are you missing GCP credentials?): {e}")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def add_to_firestore_with_retry(data: dict):
    update_time, doc_ref = db.collection(COLLECTION_NAME).add(data)
    return doc_ref

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

        doc_ref = add_to_firestore_with_retry(tingle_data)

        logger.info(f"SAVED: Document {doc_ref.id} in collection {COLLECTION_NAME}")
        return {"status": "persisted", "document_id": doc_ref.id}
    
    except Exception as e:
        logger.error(f"ERROR processing message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def liveness_probe():
    """Liveness probe: verifies the container is running."""
    return {"status": "alive"}

@app.get("/readyz")
async def readiness_probe():
    """Readiness probe: verifies dependencies are accessible."""
    try:
        if not db or not COLLECTION_NAME:
            raise ValueError("Firestore configuration or client missing")
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")