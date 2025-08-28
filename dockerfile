FROM ubuntu:24.04

# Install basic packages
RUN apt-get update && apt-get install -y \
    ffmpeg \
    python3 \
    python3-pip \
    python3-setuptools \
    vainfo \
    && rm -rf /var/lib/apt/lists/*

# Copy script
WORKDIR /app
COPY media_fixer.py /app/media_fixer.py

# Install Python dependencies
RUN pip3 install --no-cache-dir tqdm

# Make script executable
RUN chmod +x /app/media_fixer.py

# Default command (can be overridden)
CMD ["python3", "/app/media_fixer.py"]