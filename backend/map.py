import httpx
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from scripts import utils

router = APIRouter(prefix="/map", tags=["mobile-api","tilemap"])

env = utils.load_dotenv(".env")
http_client = httpx.AsyncClient(
    timeout=10.0,
)

# permanent cache map tiles
CACHE_DIR = Path("cache/map_tiles")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save_cache_file(file: Path, content: bytes):
    assert type(file) is Path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(content)

@router.get("/{z}/{x}/{y}.png")
async def get_map_tile(z: int, x: int, y: int):
    cache_file = ( CACHE_DIR / str(z) / str(x) / f"{y}.png" )
    if cache_file.exists():
        return Response(
            content=cache_file.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=2592000", "X-Map-Cache": "HIT"},
        )

    try:
        CARTO_API_KEY = env["CARTO_API_KEY"]
    except KeyError:
        raise HTTPException(status=400, detail="missing api key")

    carto_url = (
        f"https://basemaps.cartocdn.com/"
        f"rastertiles/dark_all/{z}/{x}/{y}.png"
    )
    try:
        response = await http_client.get(
            carto_url,
            params={"api_key": CARTO_API_KEY},
            headers={"User-Agent": "Museekar/1.0"},
        )
        assert response.status_code == 200
        save_cache_file(cache_file, response.content)
    except _: # write error, httpx.RequestError, AssertionError
        raise HTTPException(status=502, detail="failed to fetch map tile")


    return Response(
        content=response.content,
        media_type=response.headers.get(
            "content-type",
            "image/png",
        ),
        status_code=response.status_code,
    )
