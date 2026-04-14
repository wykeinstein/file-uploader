#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME=${1:-synology-telegram-uploader}
IMAGE_TAG=${2:-latest}

docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
echo "Built image: ${IMAGE_NAME}:${IMAGE_TAG}"
