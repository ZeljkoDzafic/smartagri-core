# Web app and API of SmartAgri core for a public deployment (docs/deployment.md).
# Accounts are on in this image (SMARTAGRI_ACCOUNTS=optional); the code's default for local use stays off.
# No proxy is trusted to name the client's address until the operator lists it in SMARTAGRI_TRUSTED_PROXIES.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend
# Dependencies pinned by requirements.lock (Python 3.12). Editable install: config/, corpus/ and eval/ are read next to
# the source tree.
COPY backend/pyproject.toml backend/requirements.lock ./
COPY backend/src ./src
RUN pip install -c requirements.lock -e ".[api,pg]"
COPY backend/config ./config
COPY backend/corpus ./corpus
COPY backend/eval ./eval
RUN useradd --create-home --uid 10001 smartagri && mkdir -p /data && chown smartagri /data
USER smartagri
ENV SMARTAGRI_ACCOUNTS=optional \
    SMARTAGRI_DB=/data/smartagri.sqlite \
    LLM_PROVIDER=template \
    EMBEDDINGS_PROVIDER=none \
    SMARTAGRI_TRUSTED_PROXIES= \
    FORWARDED_ALLOW_IPS=127.0.0.1
VOLUME /data
EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/api/health', timeout=4)"
CMD ["python", "-m", "smartagri.research_api", "--host", "0.0.0.0", "--port", "8100"]
