#!/usr/bin/env bash
# One-liner installer and runner for Media Fixer

set -e

# Default Docker image
IMAGE_NAME="yourusername/media-fixer:latest"

# Check if Docker is installed
if ! command -v docker &>/dev/null; then
    echo "❌ Docker not found. Please install Docker first."
    exit 1
fi

# Pull latest image from GitHub Container Registry / Docker Hub
echo "⬇ Pulling latest Media Fixer image..."
docker pull $IMAGE_NAME

# Run container with GPU if available
GPU_OPTION=""
if command -v nvidia-smi &>/dev/null; then
    GPU_OPTION="--gpus all"
    echo "⚙ NVIDIA GPU detected. Running with GPU support."
else
    echo "⚙ No GPU detected. Running on CPU."
fi

# Map current directory to /media in container
docker run --rm $GPU_OPTION -v "$PWD":/media $IMAGE_NAME "$@"