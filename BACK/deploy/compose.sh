#!/usr/bin/env bash
set -euo pipefail
DEPLOY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec docker compose --project-name perk-production \
  --project-directory "$DEPLOY_DIR/../BACK" \
  --env-file "$DEPLOY_DIR/production.env" \
  -f "$DEPLOY_DIR/../BACK/compose.yaml" \
  -f "$DEPLOY_DIR/compose.production.yaml" "$@"
