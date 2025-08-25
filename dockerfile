# Start from NVIDIA CUDA runtime (ensures GPU support inside container)
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# Install Python and ffmpeg with NVENC support
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Copy your script into container
COPY mf.py /app/mf.py
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Default entrypoint (can be overridden)
ENTRYPOINT ["python3", "/app/mf.py"]
