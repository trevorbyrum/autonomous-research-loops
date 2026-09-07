FROM python:3.12-slim
RUN pip install --no-cache-dir "psycopg[binary]>=3.1"
WORKDIR /app
COPY research_gateway/ /app/research_gateway/
COPY sources.example.toml /app/sources.example.toml
ENV PYTHONUNBUFFERED=1 RESEARCH_GATEWAY_LISTEN=0.0.0.0:8765
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD python3 -c "import json,urllib.request,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:8765/v1/health', timeout=4)).get('ok') else 1)"
CMD ["python3", "-m", "research_gateway.api.http"]
