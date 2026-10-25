# Prepared without Hoben credentials. C2a execution always uses network=none.
FROM python:3.14-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8
COPY requirements.txt /requirements.txt
# The public CA bundle is a build-only mount; never change TLS verification.
RUN --mount=type=secret,id=proxy_ca,required=true \
    PIP_CERT=/run/secrets/proxy_ca python -m pip install --no-cache-dir -r /requirements.txt
