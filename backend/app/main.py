import asyncio
import logging
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import router as api_router
from app.services.ram_service import RamService
from app.linux.privileges import check_privileges

# Configure backend logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ramscope.backend")

app = FastAPI(
    title="RAMScope API",
    description="Physical RAM Visualization & Monitoring Backend for Linux",
    version="1.0.0",
)

# Explicit CORS origins for Next.js development and local network access
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    logger.info(f"Incoming request: {request.method} {request.url.path}")
    try:
        response = await call_next(request)
        duration = (time.time() - start_time) * 1000
        logger.info(f"Completed {request.method} {request.url.path} with status {response.status_code} in {duration:.2f}ms")
        return response
    except Exception as exc:
        duration = (time.time() - start_time) * 1000
        logger.error(f"Failed {request.method} {request.url.path} in {duration:.2f}ms: {exc}", exc_info=True)
        raise

app.include_router(api_router, prefix="/api")

ram_service = RamService()

@app.get("/")
def root():
    status = check_privileges()
    logger.info(f"Root status queried: Linux={status.platform_is_linux}, Root={status.is_root}, Module={status.kernel_module_loaded}")
    return {
        "system": "RAMScope Physical Memory Monitoring System",
        "status": "online",
        "privileges": status.model_dump(by_alias=True),
    }

@app.websocket("/ws/live")
async def websocket_live_updates(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket /ws/live client connected")
    try:
        while True:
            ram_info = ram_service.get_ram_info()
            priv_info = check_privileges()

            payload = {
                "type": "ram_update",
                "timestamp": asyncio.get_event_loop().time(),
                "ram": ram_info.model_dump(by_alias=True),
                "status": priv_info.model_dump(by_alias=True),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(1.5)  # 1.5s refresh interval
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/live client disconnected")
    except Exception as exc:
        logger.warning(f"WebSocket /ws/live error: {exc}")

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting RAMScope FastAPI server on http://0.0.0.0:8000")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
