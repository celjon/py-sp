FROM python:3.11-slim

# Create non-root user for security
RUN groupadd -r antispam && useradd -r -g antispam -m antispam

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy and install Python dependencies
COPY requirements.txt requirements-pytorch.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r requirements-pytorch.txt

# Copy application code with proper ownership
COPY --chown=antispam:antispam . .

# Create necessary directories
RUN mkdir -p logs models cache \
    && chown -R antispam:antispam logs models cache

# Create and set permissions for HuggingFace cache directory
RUN mkdir -p /home/antispam/.cache \
    && chown -R antispam:antispam /home/antispam

# Set proper permissions
RUN chmod -R 755 /app \
    && chmod 750 /app/logs /app/models /app/cache

# Switch to non-root user
USER antispam

# Environment variables
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HF_HOME="/home/antispam/.cache"
ENV TRANSFORMERS_CACHE="/home/antispam/.cache"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

CMD ["python", "-m", "src.main"]



