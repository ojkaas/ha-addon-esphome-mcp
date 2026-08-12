ARG BUILD_FROM
# The MCP server no longer compiles firmware itself — it delegates every
# build/flash/validate/logs call to the ESPHome Device Builder dashboard
# running in the official ESPHome add-on. So there's no need for the heavy
# ESPHome (Debian/glibc + ESP toolchains + PlatformIO) base image or its
# pinned esphome version.
#
# HA Supervisor only accepts base images from trusted registries, so we build
# on the standard HA Alpine base (set in build.yaml) and add just Python + pip
# + bash. Pure-Python + musllinux wheels (aiohttp, pydantic-core) install
# without a compiler.
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip bash

COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy server code
COPY server/ /opt/server/
COPY run.sh /opt/

RUN chmod a+x /opt/run.sh

WORKDIR /opt

CMD ["/opt/run.sh"]
