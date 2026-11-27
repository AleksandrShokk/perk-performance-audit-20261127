#!/usr/bin/env bash
set -euo pipefail
umask 077
DEPLOY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BACKUP_DIR="$DEPLOY_DIR/../backups"
install -d -m 0700 "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PART="$BACKUP_DIR/perk-$STAMP.dump.partial"
FINAL="$BACKUP_DIR/perk-$STAMP.dump"
"$DEPLOY_DIR/compose.sh" exec -T postgres pg_dump -U perk -d perk -Fc --no-owner > "$PART"
test -s "$PART"
mv -- "$PART" "$FINAL"
sha256sum "$FINAL" > "$FINAL.sha256"
# Secrets are needed to decrypt marketplace tokens and MFA in a restored database.
tar -czf "$BACKUP_DIR/perk-$STAMP-secrets.tar.gz" -C "$DEPLOY_DIR/../BACK" .secrets -C "$DEPLOY_DIR" production.env
printf 'Backup created: %s\n' "$STAMP"
# Keep seven daily copies; a separate off-server copy is required as well.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'perk-20*' -mtime +7 -delete
