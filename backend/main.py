from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from backend import api, rolly, map


app = FastAPI()

app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"], 
)
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,
    compresslevel=5
)

app.include_router(api.router)
app.include_router(rolly.router)
app.include_router(map.router)
