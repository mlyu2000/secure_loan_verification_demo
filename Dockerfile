# Shared Python runtime for engine + credit-memo-mcp.
# The chart runs two containers from this image with different commands/ports.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY engine /app/engine
COPY mcp-server /app/mcp-server
COPY mockdata /app/mockdata
# engine entrypoint
RUN printf '#!/bin/sh\nexec python -m engine.main\n' > /app/run-engine.sh \
    && printf '#!/bin/sh\ncd /app/mcp-server && exec python -m uvicorn server:app --host 0.0.0.0 --port 8000\n' > /app/run-mcp.sh \
    && chmod +x /app/run-engine.sh /app/run-mcp.sh
EXPOSE 8080 8000
CMD ["/app/run-engine.sh"]
