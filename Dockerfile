FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    elasticsearch>=9.0.2 \
    fastmcp>=2.10.4 \
    httpx>=0.27.0 \
    pydantic>=2.11.7 \
    python-dotenv>=1.1.1 \
    requests>=2.32.4

# Copy application files
COPY wsdot_server.py .
COPY events_read_server.py .
COPY events_write_server.py .
COPY elastic_agent_example.py .
COPY utilities.py .
COPY config.py .
COPY data/ data/
COPY setup/ setup/

# Set environment variable for unbuffered output
ENV PYTHONUNBUFFERED=1

# Default command (can be overridden in docker-compose)
CMD ["python", "wsdot_server.py"]
