FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Installeer dependencies + Google Chrome (niet Chromium — nodig voor undetected-chromedriver)
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    libasound2 \
    libnss3 \
    libxss1 \
    libgtk-3-0 \
    xdg-utils \
    wget \
    curl \
    unzip \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installeer Google Chrome stable
RUN wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app
CMD ["python", "main.py"]
