# Use Python 3.12 slim image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libpq-dev \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY ct_upload_platform .

# Create non-root user and ensure media subdirectories are writable
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/media/examination_study_sets \
    && chown -R appuser:appuser /app
USER appuser

# Default command: run gunicorn
CMD ["gunicorn", "ct_upload_platform.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
