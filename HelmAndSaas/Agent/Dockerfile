# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY agent/ ./agent/

# Non-root user (security best practice)
RUN useradd -m -u 1000 sadmc
USER sadmc

# Start the agent
CMD ["python", "-m", "agent"]
