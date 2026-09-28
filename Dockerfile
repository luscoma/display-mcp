# syntax=docker/dockerfile:1
#
# display-mcp as an OCI image: the same process the systemd unit runs, with
# the fonts baked in so preview() works on first start and the state directory
# as the only thing that outlives a container. deploy/CONTAINER.md is the
# how-to; this file is only the build.
#
#   docker build -t display-mcp .
#
# The fonts stage downloads from GitHub at build time. With the seven files
# already on disk (deploy/fetch-fonts.sh ./fonts), skip the download:
#
#   docker build --build-context fonts=./fonts -t display-mcp .

ARG PYTHON_VERSION=3.12

# --- fonts ------------------------------------------------------------------
# One implementation of the download, deploy/fetch-fonts.sh, shared with
# setup.sh and local dev. `fonts` is a bare stage holding just the .ttf files
# at its root, so --build-context fonts=DIR can stand in for it.

FROM debian:bookworm-slim AS fonts-fetch
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
COPY deploy/fetch-fonts.sh /usr/local/bin/fetch-fonts.sh
RUN fetch-fonts.sh /out

FROM scratch AS fonts
COPY --from=fonts-fetch /out/ /

# --- build ------------------------------------------------------------------
# A non-editable install into a venv, the same thing setup.sh does. The
# pyproject force-includes docs/SPEC.md and samples/display.json into the
# wheel, so both have to be in the build context.

FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/display-mcp/venv
WORKDIR /src
COPY pyproject.toml README.md ./
COPY docs/SPEC.md docs/SPEC.md
COPY samples/ samples/
COPY src/ src/
RUN /opt/display-mcp/venv/bin/pip install .

# --- runtime ----------------------------------------------------------------

FROM python:${PYTHON_VERSION}-slim

ARG UID=10001
RUN groupadd --system --gid "$UID" display-mcp \
 && useradd --system --uid "$UID" --gid display-mcp --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin display-mcp \
 && install -d -o display-mcp -g display-mcp -m 0755 /var/lib/display-mcp

COPY --from=build /opt/display-mcp/venv /opt/display-mcp/venv
COPY --from=fonts / /opt/display-mcp/fonts/

# The defaults match the systemd unit, except the panel bind: the unit's
# default is a LAN address this image cannot know. 127.0.0.1 is the safe
# default; set DISPLAY_MCP_PANEL_BIND=<lan-ip>,127.0.0.1 at run time. main.py
# refuses a wildcard bind, in a container as anywhere else.
ENV PATH=/opt/display-mcp/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY_MCP_PANEL_BIND=127.0.0.1 \
    DISPLAY_MCP_PANEL_PORT=8080 \
    DISPLAY_MCP_MCP_HOST=127.0.0.1 \
    DISPLAY_MCP_MCP_PORT=8001 \
    DISPLAY_MCP_MCP_PATH=/mcp \
    DISPLAY_MCP_STATE_DIR=/var/lib/display-mcp \
    DISPLAY_MCP_FONT_DIR=/opt/display-mcp/fonts

# Fail the build, not the first preview(), if the fonts or the sample are off.
RUN display-mcp-cli check /opt/display-mcp/venv/lib/python*/site-packages/display_mcp/prompts/sample.json

USER display-mcp
WORKDIR /var/lib/display-mcp
VOLUME ["/var/lib/display-mcp"]
EXPOSE 8080 8001

# /healthz always answers 200 while the process is up; healthy here also means
# the fonts loaded and the state directory takes writes. The panel always
# binds 127.0.0.1 in the shipped configs, so that is where this looks.
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import json,os,urllib.request as u; p=os.environ.get('DISPLAY_MCP_PANEL_PORT','8080'); h=json.load(u.urlopen(f'http://127.0.0.1:{p}/healthz',timeout=4)); raise SystemExit(0 if h['fonts_loaded'] and h['state_dir_writable'] else 1)"]

ENTRYPOINT ["display-mcp"]
