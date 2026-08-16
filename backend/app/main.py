import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import ensure_indexes, get_db
from app.routes import rules, stats, webhook
from app.workers.dm_worker import run_worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db = get_db()
    app.state.db = db
    await ensure_indexes(db)

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(run_worker_loop(db, stop_event))

    yield

    stop_event.set()
    await asyncio.wait_for(worker_task, timeout=5)


app = FastAPI(title="LinkPlease Intern Assignment", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rules.router)
app.include_router(webhook.router)
app.include_router(stats.router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "linkplease-backend"}
