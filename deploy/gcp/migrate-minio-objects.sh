#!/usr/bin/env bash
# One-off: copy every object from the retired MinIO volume into RustFS.
#
# The object store moved from MinIO to RustFS on 2026-09-26 (the MinIO images
# are no longer downloadable). RustFS starts on a new, empty volume, while the
# documents Postgres already knows about still sit in `mnemos_miniodata`. This
# starts the old server once more on that volume, from the image already on
# this machine, and copies each bucket's objects across with their keys and
# content types unchanged. Safe to re-run: an object is simply written again.
#
#   deploy/gcp/migrate-minio-objects.sh                          # the VM
#   COMPOSE="docker compose" deploy/gcp/migrate-minio-objects.sh # a local stack
#
# Run it after the stack is on RustFS. The old volume is left in place; delete
# it (`docker volume rm mnemos_miniodata`) once the copy has been checked.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read -r -a compose <<<"${COMPOSE:-$here/compose.sh}"
volume=mnemos_miniodata
network=mnemos_default
image=minio/minio:latest
old=mnemos-minio-migrate

if ! docker volume inspect "$volume" >/dev/null 2>&1; then
  echo "no $volume volume here: nothing to migrate"
  exit 0
fi
if ! docker image inspect "$image" >/dev/null 2>&1; then
  echo "$image is not on this machine, and it can no longer be pulled" >&2
  exit 1
fi
if [[ -n "$(docker ps -q --filter "volume=$volume")" ]]; then
  echo "a container is still using $volume; stop it first (compose up --remove-orphans)" >&2
  exit 1
fi

"${compose[@]}" up -d --wait rustfs
"${compose[@]}" run --rm rustfs-init

# The old volume was initialised with the root pair the stack still uses (the
# base file's development pair, or .env.prod's). Passed by name, not as
# `-e NAME=value`, so the values never appear in a process list.
creds=$("${compose[@]}" config --format json | jq -r '.services.rustfs.environment | .RUSTFS_ACCESS_KEY, .RUSTFS_SECRET_KEY')
MINIO_ROOT_USER=$(sed -n 1p <<<"$creds")
MINIO_ROOT_PASSWORD=$(sed -n 2p <<<"$creds")
export MINIO_ROOT_USER MINIO_ROOT_PASSWORD
unset creds

trap 'docker rm -f "$old" >/dev/null 2>&1 || true' EXIT
docker run -d --rm --name "$old" --network "$network" -v "$volume:/data" \
  -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD "$image" server /data >/dev/null
for _ in $(seq 1 30); do
  docker exec "$old" mc ready local >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$old" mc ready local >/dev/null

# Inside the api image: it already has boto3 and the stack's credentials.
"${compose[@]}" run --rm --no-deps -T -e MNEMOS_MIGRATE_FROM="http://$old:9000" api python - <<'PY'
import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def client(url: str):
    return boto3.client(
        "s3",
        endpoint_url=url,
        aws_access_key_id=os.environ["MNEMOS_OBJECT_ACCESS_KEY"],
        aws_secret_access_key=os.environ["MNEMOS_OBJECT_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


src = client(os.environ["MNEMOS_MIGRATE_FROM"])
dst = client(os.environ["MNEMOS_OBJECT_ENDPOINT"])


def keys(s3, bucket: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", ()):
            found[obj["Key"]] = obj["Size"]
    return found


for bucket in [b["Name"] for b in src.list_buckets()["Buckets"]]:
    try:
        dst.head_bucket(Bucket=bucket)
    except ClientError:
        dst.create_bucket(Bucket=bucket)
    wanted = keys(src, bucket)
    for key in wanted:
        obj = src.get_object(Bucket=bucket, Key=key)
        dst.put_object(
            Bucket=bucket, Key=key, Body=obj["Body"].read(), ContentType=obj["ContentType"]
        )
    have = keys(dst, bucket)
    missing = [k for k, size in wanted.items() if have.get(k) != size]
    if missing:
        raise SystemExit(f"{bucket}: {len(missing)} objects did not arrive intact: {missing[:5]}")
    print(f"{bucket}: {len(wanted)} objects copied and checked")
PY
