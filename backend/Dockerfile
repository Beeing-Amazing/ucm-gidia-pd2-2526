FROM python:3.13-slim

# ---
# SETUP PYTHON
# ---
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ---
# SETUP JAVA (pyspark)
# ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# ---
# SETUP APP
# ---
WORKDIR /src

COPY ./pyproject.toml .
COPY ./uv.lock .
RUN uv sync --quiet --frozen --no-cache \
        --index https://download.pytorch.org/whl/cpu

