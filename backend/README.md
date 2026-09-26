entrypoints here are not supposed to be run as is.
paths and imports are relative to positions inside docker.

to wake the backend, run `docker compose up`
using the provided compose file at the project root.

> [!WARNING]
> At this moment, these scripts do not safecheck whether download scripts have been run.
> Please run those first as described in the setup process.

the companion app will query the backend to produce a tilemap. please provide an API key in project root `.env` :
```
CARTO_API_KEY="numbers"
```

