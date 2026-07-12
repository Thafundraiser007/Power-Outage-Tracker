# Playwright's official image already has Chromium plus every OS-level
# dependency it needs (fonts, codecs, etc) preinstalled -- this avoids
# the "apt install fails on Render/Railway" headache that plain
# `playwright install --with-deps` can run into on some hosts.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data logs

ENV FLASK_DEBUG=0
EXPOSE 5000

# Use gunicorn in production rather than Flask's dev server.
RUN pip install --no-cache-dir gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:application"]
