ARG BUILD_FROM
FROM ${BUILD_FROM}

# Base image (ghcr.io/esphome/esphome) is Debian/glibc and already provides
# esphome + PlatformIO with working ESP toolchains. We only add the MCP
# server's Python dependencies on top.
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy server code
COPY server/ /opt/server/
COPY run.sh /opt/

RUN chmod a+x /opt/run.sh

WORKDIR /opt

# The official esphome image ships an ENTRYPOINT and a HEALTHCHECK that probe
# the ESPHome dashboard. We run the MCP server instead, so both must go —
# otherwise the failing dashboard healthcheck makes Supervisor restart the
# add-on on a ~60s loop.
ENTRYPOINT []

# The healthcheck must be a real, passing probe — NOT `HEALTHCHECK NONE`.
# Supervisor derives the add-on state from `docker inspect .Config.Healthcheck`,
# and per the Docker image spec `NONE` is encoded as a populated field
# ({"Test": ["NONE"]}), not an absent one. Supervisor therefore reads "this
# container has a healthcheck" and parks the add-on in `startup` until Docker
# emits a health event — which a disabled healthcheck never does, so the UI
# shows "Starting" forever even though the server is serving fine.
ENV MCP_PORT=8098
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
    CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('MCP_PORT','8098')+'/health',timeout=4)"

CMD ["/opt/run.sh"]
