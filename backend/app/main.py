import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .config import INBOX_DIR, LAW_LIBRARY_DIR, REPORTS_DIR, STATUTES_DIR, TEMPLATES_DIR
from .db import Base, engine
from .routers import actions, changes, flags, graph, library


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    for d in (INBOX_DIR, STATUTES_DIR, TEMPLATES_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # Self-contained: the app checks for statute updates on its own
    # schedule (see scheduler.py) rather than needing an external cron,
    # so this works the same locally or deployed.
    scheduler_task = asyncio.create_task(scheduler.run_scheduler_loop())
    try:
        yield
    finally:
        scheduler_task.cancel()


app = FastAPI(title="HuatHuat", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for _d in (INBOX_DIR, STATUTES_DIR, TEMPLATES_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")
# Read-only: lets the frontend embed a real PDF (<iframe src="/library/templates/x.pdf">)
# for document preview, "like Google Drive". Never used to write anything.
app.mount("/library", StaticFiles(directory=str(LAW_LIBRARY_DIR)), name="library")


app.include_router(library.router)
app.include_router(changes.router)
app.include_router(flags.router)
app.include_router(graph.router)
app.include_router(actions.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
