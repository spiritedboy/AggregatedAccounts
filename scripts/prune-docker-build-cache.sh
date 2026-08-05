#!/usr/bin/env bash
set -euo pipefail

cache_limit="${DOCKER_BUILD_CACHE_LIMIT:-5gb}"

echo "[$(date --iso-8601=seconds)] Docker build cache maintenance started (limit=$cache_limit)"
docker buildx prune --all --force --max-used-space "$cache_limit"
docker system df
echo "[$(date --iso-8601=seconds)] Docker build cache maintenance completed"
