import os
import json
import logging
import sys
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import pubsub_v1
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

logger = logging.getLogger("ingestor")

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
TOPIC_ID = os.getenv("PUB_SUB_TOPIC_ID")
API_KEY_SECRET = os.getenv("API_KEY", "dev-secret-key")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

if not PROJECT_ID or not TOPIC_ID:
    raise RuntimeError("Environment variables GOOGLE_CLOUD_PROJECT and PUB_SUB_TOPIC_ID must be set.")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != API_KEY_SECRET:
        raise HTTPException(status_code=403, detail="Could not validate API key")
    return api_key

# Global state
publisher = None
topic_path = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global publisher, topic_path
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    yield
    logger.info("Shutting down Pub/Sub publisher...")

app = FastAPI(title="Project S.E.N.S.E. Ingestor", lifespan=lifespan)
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

class Tingle(BaseModel):
    lat: float
    lng: float

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def publish_with_retry(data: bytes):
    future = publisher.publish(topic_path, data)
    return future.result()

@app.post("/tingle")
async def receive_tingle(tingle: Tingle, api_key: str = Depends(get_api_key)):
    try:
        data = json.dumps(tingle.model_dump()).encode("utf-8")
        message_id = publish_with_retry(data)

        logger.info(f"Successfully published tingle to Pub/Sub. Message ID: {message_id}")
        return {"status": "dispatched", "message_id": message_id}
    except Exception as e:
        logger.error(f"Error publishing message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz")
async def liveness_probe():
    """Liveness probe: verifies the container is running."""
    return {"status": "alive"}

@app.get("/readyz")
async def readiness_probe():
    """Readiness probe: verifies dependencies are accessible."""
    try:
        if not PROJECT_ID or not TOPIC_ID or not publisher:
            raise ValueError("Pub/Sub configuration or client missing")
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")