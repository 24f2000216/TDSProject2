# Multi-stage: Build browsers → Production Python
FROM node:20-bookworm-slim AS playwright-base

# Install ALL browser dependencies
RUN apt-get update && apt-get install -y \
    # Playwright/Chromium requirements
    wget gnupg ca-certificates fonts-liberation libasound2 \
    libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
    libdrm2 libexpat1 libgbm1 libgcc1 libglib2.0-0 libnspr4 \
    libnss3 libpango-1.0-0 libstdc++6 libx11-6 libx11-xcb1 \
    libxcb1 libxcomposite1 libxcursor1 libxdamage1 libxext6 \
    libxfixes3 libxi6 libxrandr2 libxss1 libxtst6 lsb-release \
    xdg-utils libgobject-2.0-0 libnssutil3 libsmime3 libatspi2.0-0 \
    libxkbcommon0 libcairo2 libpangoft2-1.0-0 libgtk-3-0 \
    libgdk-pixbuf-2.0-0 libgtk-3-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /playwright
RUN npm init -y && \
    npm install playwright@1.44.1 && \
    npx playwright install --with-deps chromium

# Production image
FROM python:3.11-slim-bookworm

# Copy pre-built browsers
COPY --from=playwright-base /ms-playwright /ms-playwright
COPY --from=playwright-base /playwright/node_modules/playwright /playwright/node_modules/playwright

# Install Python runtime deps (minimal)
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libatspi2.0-0 libxshmfence1 libgl1 libxss1 libxtst6 \
    libgobject-2.0-0 libnssutil3 libsmime3 libcups2 \
    && rm -rf /var/lib/apt/lists/*

# Playwright config
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# App setup
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY scraper_playwright.py scraper.py
COPY main.py .
COPY *.md ./

# Create cache dir
RUN mkdir -p /app/.scraper_cache

# HF Spaces port
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

# Run production server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
