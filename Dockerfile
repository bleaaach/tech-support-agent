FROM docker.m.daocloud.io/library/python:3.11-slim

WORKDIR /app

# Install minimal system deps (no compile needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps with Aliyun mirror for speed
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

# Copy source
COPY . .

EXPOSE 8000 8501

# supervisord to run both FastAPI + Streamlit
RUN pip install --no-cache-dir supervisor \
    && mkdir -p /var/log/supervisor /var/run /etc/supervisor/conf.d

COPY <<'EOF' /etc/supervisor/conf.d/tech-agent.conf
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid

[program:fastapi]
command=python -m uvicorn agent.main:app --host 0.0.0.0 --port 8000
directory=/app
stdout_logfile=/var/log/supervisor/fastapi.log
stderr_logfile=/var/log/supervisor/fastapi.err.log
autostart=true
autorestart=true

[program:streamlit]
command=streamlit run ui/app.py --server.port 8501 --server.address 0.0.0.0
directory=/app
stdout_logfile=/var/log/supervisor/streamlit.log
stderr_logfile=/var/log/supervisor/streamlit.err.log
autostart=true
autorestart=true
EOF

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["/usr/local/bin/supervisord", "-c", "/etc/supervisor/conf.d/tech-agent.conf"]
