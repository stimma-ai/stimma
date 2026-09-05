FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM debian:bookworm-slim
ARG BOOTSTRAP_VERSION=1.0.0
ARG BOOTSTRAP_RECIPE=local
LABEL org.opencontainers.image.title="Stimma headless bootstrap" \
      org.opencontainers.image.source="https://github.com/stimma-ai/stimma" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version=$BOOTSTRAP_VERSION \
      ai.stimma.bootstrap.recipe=$BOOTSTRAP_RECIPE
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates bash python3 python3-venv python3-pip ffmpeg curl git jq ripgrep \
    unzip xz-utils tar tini minisign tzdata libgomp1 libglib2.0-0 libpango-1.0-0 \
    libpangoft2-1.0-0 fonts-dejavu-core libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home stimma \
    && mkdir -p /data /opt/stimma && chown stimma:stimma /data
COPY --from=uv /uv /uvx /usr/local/bin/
COPY packaging/headless/supervisor.py /opt/stimma/supervisor.py
COPY packaging/headless/updater.pub /opt/stimma/updater.pub
COPY packaging/headless/stimma-server /usr/local/bin/stimma-server
RUN printf '%s\n' "$BOOTSTRAP_VERSION" > /opt/stimma/bootstrap-version \
    && chmod +x /usr/local/bin/stimma-server
ENV STIMMA_HEADLESS=1 STIMMA_DATA_DIR=/data/state STIMMA_CACHE_DIR=/data/cache \
    STIMMA_HEADLESS_ROOT=/data TZ=UTC PYTHONUNBUFFERED=1
USER stimma
WORKDIR /data
VOLUME /data
EXPOSE 9193
HEALTHCHECK --start-period=10m --interval=30s --timeout=5s --retries=3 CMD ["stimma-server", "health"]
ENTRYPOINT ["/usr/bin/tini", "--", "stimma-server"]
CMD ["serve"]
