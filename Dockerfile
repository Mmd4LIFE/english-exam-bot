FROM python:3.12-slim

# System deps:
#  - poppler-utils → pdftotext / pdftoppm (answer-key parsing + OCR rendering)
#  - libpq5        → psycopg runtime
#  - fonts         → matplotlib chart rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        libpq5 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the entrypoint is executable inside the image (independent of the
# file mode on the host / in git), and create a non-root runtime user.
RUN chmod +x ./docker/entrypoint.sh \
    && useradd -m appuser && chown -R appuser /app
USER appuser

ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["bot"]
