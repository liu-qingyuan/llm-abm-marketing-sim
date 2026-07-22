#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RELEASE_CONTRACT=""

DEPLOY_HOST="${ABM_DEPLOY_HOST:-q1ngyuan.top}"
DOMAIN="${ABM_DEPLOY_DOMAIN:-abm.q1ngyuan.top}"
REMOTE_ROOT="${ABM_DEPLOY_REMOTE_ROOT:-/opt/llm-abm-marketing-sim-report}"
PORT="${ABM_DEPLOY_PORT:-18083}"
CONTAINER_NAME="${ABM_DEPLOY_CONTAINER_NAME:-abm-research-report}"
IMAGE="${ABM_DEPLOY_IMAGE:-nginx:1.27-alpine}"
PYTHON="${ABM_DEPLOY_PYTHON:-python3}"
SOURCE_DIR=""
RELEASE_ID=""
LOCAL_SNAPSHOT_DIR=""

usage() {
  printf 'Usage: %s --contract <formal-release-contract> --source-dir <approved-run-directory> --release-id <release-id>\n' "$0" >&2
}

fail() {
  printf 'deploy error: %s\n' "$*" >&2
  exit 1
}

while (( $# > 0 )); do
  case "$1" in
    --contract)
      (( $# >= 2 )) || { usage; fail "--contract requires a value"; }
      RELEASE_CONTRACT="$2"
      shift 2
      ;;
    --source-dir)
      (( $# >= 2 )) || { usage; fail "--source-dir requires a value"; }
      SOURCE_DIR="$2"
      shift 2
      ;;
    --release-id)
      (( $# >= 2 )) || { usage; fail "--release-id requires a value"; }
      RELEASE_ID="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage
      fail "unknown argument: $1"
      ;;
  esac
done

if [[ -z "${RELEASE_CONTRACT}" || -z "${SOURCE_DIR}" || -z "${RELEASE_ID}" ]]; then
  usage
  fail "--contract, --source-dir, and --release-id are all required"
fi

[[ "${DOMAIN}" =~ ^[A-Za-z0-9.-]+$ ]] || fail "invalid domain: ${DOMAIN}"
[[ "${PORT}" =~ ^[0-9]+$ ]] || fail "invalid port: ${PORT}"
(( PORT >= 1024 && PORT <= 65535 )) || fail "port must be between 1024 and 65535"
[[ "${REMOTE_ROOT}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "invalid remote root: ${REMOTE_ROOT}"
[[ "${CONTAINER_NAME}" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "invalid container name: ${CONTAINER_NAME}"
[[ "${IMAGE}" =~ ^[A-Za-z0-9._/:@-]+$ ]] || fail "invalid image reference: ${IMAGE}"
[[ "${RELEASE_ID}" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "invalid release id: ${RELEASE_ID}"
CANONICAL_SOURCE_DIR="$(cd -- "${SOURCE_DIR}" 2>/dev/null && pwd -P)" || fail "source directory does not exist"
cleanup_local_snapshot() {
  local snapshot_dir="${LOCAL_SNAPSHOT_DIR}"
  [[ -n "${snapshot_dir}" && -d "${snapshot_dir}" ]] || return 0
  if command -v chflags >/dev/null 2>&1; then
    chflags -R nouchg,noschg "${snapshot_dir}" 2>/dev/null || true
  fi
  chmod -R u+w "${snapshot_dir}" 2>/dev/null || true
  if ! rm -r -- "${snapshot_dir}"; then
    printf 'deploy error: cannot remove local release snapshot %s\n' "${snapshot_dir}" >&2
    return 1
  fi
  LOCAL_SNAPSHOT_DIR=""
}
LOCAL_SNAPSHOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/abm-report-deploy.XXXXXX")"
trap cleanup_local_snapshot EXIT
COPYFILE_DISABLE=1 cp -R "${CANONICAL_SOURCE_DIR}/." "${LOCAL_SNAPSHOT_DIR}/"

"${PYTHON}" "${SCRIPT_DIR}/validate_abm_report_release.py" \
  --repo-root "${REPO_ROOT}" \
  --contract "${RELEASE_CONTRACT}" \
  --source-dir "${SOURCE_DIR}" \
  --snapshot-dir "${LOCAL_SNAPSHOT_DIR}" \
  --require-formal-production
SOURCE_DIR="${LOCAL_SNAPSHOT_DIR}"
find "${SOURCE_DIR}" -type d -exec chmod a-w {} +
find "${SOURCE_DIR}" -type f -exec chmod a-w {} +

LOCAL_REPORT_SHA="$(shasum -a 256 "${SOURCE_DIR}/report.html" | awk '{print $1}')"
LOCAL_MANIFEST_SHA="$(shasum -a 256 "${SOURCE_DIR}/artifact_manifest.json" | awk '{print $1}')"
REMOTE_RELEASE="${REMOTE_ROOT}/releases/${RELEASE_ID}"

PREVIOUS_RELEASE_FILE="$(mktemp)"
if ssh "${DEPLOY_HOST}" bash -s -- "${REMOTE_ROOT}" > "${PREVIOUS_RELEASE_FILE}" <<'READ_CURRENT'
set -euo pipefail
remote_root="$1"
current="${remote_root}/current"
[[ -L "${current}" ]] || exit 0
previous="$(readlink -f "${current}")"
case "${previous}" in
  "${remote_root}"/releases/*) printf '%s\n' "${previous}" ;;
  *) printf 'deploy error: current points outside managed releases: %s\n' "${previous}" >&2; exit 1 ;;
esac
READ_CURRENT
then
  :
else
  rm -f "${PREVIOUS_RELEASE_FILE}"
  fail "cannot read current managed release"
fi
PREVIOUS_RELEASE="$(<"${PREVIOUS_RELEASE_FILE}")"
rm -f "${PREVIOUS_RELEASE_FILE}"

printf 'Uploading %s to %s:%s\n' "${SOURCE_DIR}" "${DEPLOY_HOST}" "${REMOTE_RELEASE}"
ssh "${DEPLOY_HOST}" bash -s -- "${REMOTE_RELEASE}" <<'PREPARE_RELEASE'
set -euo pipefail
remote_release="$1"
[[ ! -e "${remote_release}" ]] || {
  printf 'deploy error: release already exists: %s\n' "${remote_release}" >&2
  exit 1
}
install -d -m 755 "${remote_release}"
PREPARE_RELEASE

upload_complete=0
cleanup_partial_upload() {
  status=$?
  trap - EXIT
  if (( status != 0 && upload_complete == 0 )); then
    ssh "${DEPLOY_HOST}" bash -s -- "${REMOTE_RELEASE}" <<'CLEAN_PARTIAL' || true
set -euo pipefail
remote_release="$1"
[[ -d "${remote_release}" ]] && rm -r -- "${remote_release}"
CLEAN_PARTIAL
  fi
  cleanup_local_snapshot || true
  exit "${status}"
}
trap cleanup_partial_upload EXIT

COPYFILE_DISABLE=1 tar --no-xattrs -C "${SOURCE_DIR}" -czf - . \
  | ssh "${DEPLOY_HOST}" "tar -xzf - -C '${REMOTE_RELEASE}'"
upload_complete=1
trap cleanup_local_snapshot EXIT

ssh "${DEPLOY_HOST}" bash -s -- \
  "${REMOTE_ROOT}" \
  "${REMOTE_RELEASE}" \
  "${PREVIOUS_RELEASE}" \
  "${DOMAIN}" \
  "${PORT}" \
  "${CONTAINER_NAME}" \
  "${IMAGE}" \
  "${LOCAL_REPORT_SHA}" <<'REMOTE_DEPLOY'
set -euo pipefail

remote_root="$1"
remote_release="$2"
previous_release="$3"
domain="$4"
port="$5"
container_name="$6"
image="$7"
report_sha="$8"

managed_marker="# managed-by: llm-abm-marketing-sim deploy_abm_report.sh"
site_available="/etc/nginx/sites-available/${domain}"
site_enabled="/etc/nginx/sites-enabled/${domain}"
candidate_name="${container_name}-candidate"
site_backup=""
site_existed=0
site_written=0
switched=0

atomic_current() {
  target="$1"
  temporary_link="${remote_root}/.current.$$.tmp"
  ln -s "${target}" "${temporary_link}"
  mv -Tf "${temporary_link}" "${remote_root}/current"
}

wait_healthy() {
  target_container="$1"
  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${target_container}" 2>/dev/null || true)"
    [[ "${health}" == "healthy" ]] && return 0
    sleep 2
  done
  docker logs --tail 80 "${target_container}" >&2 || true
  return 1
}

rollback() {
  set +e
  if [[ -n "${previous_release}" && -f "${previous_release}/report.html" ]]; then
    previous_report_sha="$(sha256sum "${previous_release}/report.html" | awk '{print $1}')"
    sed -i \
      "s/X-Artifact-SHA256 \"[a-f0-9]\\{64\\}\"/X-Artifact-SHA256 \"${previous_report_sha}\"/" \
      "${remote_root}/nginx/default.conf"
  fi
  if (( switched == 1 )); then
    if [[ -n "${previous_release}" ]]; then
      atomic_current "${previous_release}"
      docker compose -f "${remote_root}/compose.yml" up -d --force-recreate
      wait_healthy "${container_name}"
    else
      docker compose -f "${remote_root}/compose.yml" down
      rm -f "${remote_root}/current"
    fi
  fi
  if [[ -n "${site_backup}" && -f "${site_backup}" ]]; then
    install -m 644 "${site_backup}" "${site_available}"
  elif (( site_written == 1 && site_existed == 0 )); then
    rm -f "${site_enabled}" "${site_available}"
  fi
  nginx -t && systemctl reload nginx
}

finish() {
  status=$?
  trap - EXIT
  docker rm -f "${candidate_name}" >/dev/null 2>&1 || true
  if (( status != 0 )); then
    rollback
  fi
  [[ -z "${site_backup}" ]] || rm -f "${site_backup}"
  exit "${status}"
}
trap finish EXIT

if [[ -e "${site_available}" ]]; then
  site_existed=1
  grep -Fq "${managed_marker}" "${site_available}" || {
    printf 'deploy error: refusing to overwrite unmanaged nginx site %s\n' "${site_available}" >&2
    exit 1
  }
  site_backup="$(mktemp)"
  cp "${site_available}" "${site_backup}"
fi
if [[ -e "${site_enabled}" || -L "${site_enabled}" ]]; then
  [[ -L "${site_enabled}" ]] || {
    printf 'deploy error: refusing to overwrite unmanaged nginx enabled site %s\n' "${site_enabled}" >&2
    exit 1
  }
  enabled_target="$(readlink -f "${site_enabled}" 2>/dev/null || true)"
  [[ "${enabled_target}" == "${site_available}" && "${site_existed}" == "1" ]] || {
    printf 'deploy error: refusing to overwrite unmanaged nginx enabled site %s\n' "${site_enabled}" >&2
    exit 1
  }
fi

install -d -m 755 "${remote_root}/nginx" "${remote_root}/tls" "${remote_root}/releases"
[[ "${report_sha}" =~ ^[a-f0-9]{64}$ ]] || {
  printf 'deploy error: invalid approved report SHA-256\n' >&2
  exit 1
}
find "${remote_release}" -type l -print -quit | grep -q . && {
  printf 'deploy error: uploaded release contains a symlink\n' >&2
  exit 1
}
find "${remote_release}" -type d -exec chmod 755 {} +
find "${remote_release}" -type f -exec chmod 644 {} +
uploaded_report_sha="$(sha256sum "${remote_release}/report.html" | awk '{print $1}')"
[[ "${uploaded_report_sha}" == "${report_sha}" ]] || {
  printf 'deploy error: uploaded report checksum mismatch\n' >&2
  exit 1
}

cat > "${remote_root}/nginx/default.conf" <<'CONTAINER_NGINX'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index report.html;

    gzip on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/csv application/json application/javascript image/svg+xml;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Cache-Control "no-cache" always;

    location = /healthz {
        default_type text/plain;
        return 200 "ok\n";
    }
    location = / { try_files /report.html =404; }
    location = /report.html {
        add_header X-Artifact-SHA256 "__REPORT_SHA__" always;
        try_files $uri =404;
    }
    location ~* \.csv$ {
        default_type text/csv;
        charset utf-8;
        try_files $uri =404;
    }
    location / { try_files $uri =404; }
}
CONTAINER_NGINX
sed -i "s/__REPORT_SHA__/${report_sha}/g" "${remote_root}/nginx/default.conf"

docker rm -f "${candidate_name}" >/dev/null 2>&1 || true
docker run -d \
  --name "${candidate_name}" \
  --read-only \
  --tmpfs /var/cache/nginx \
  --tmpfs /var/run \
  --health-cmd 'wget -qO- http://127.0.0.1/healthz | grep -qx ok' \
  --health-interval 2s \
  --health-timeout 3s \
  --health-retries 5 \
  -v "${remote_release}:/usr/share/nginx/html:ro" \
  -v "${remote_root}/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" \
  "${image}" >/dev/null
wait_healthy "${candidate_name}"
docker exec "${candidate_name}" wget -qO- http://127.0.0.1/healthz | grep -qx ok
docker exec "${candidate_name}" test -f /usr/share/nginx/html/report.html

compose_tmp="$(mktemp "${remote_root}/.compose.XXXXXX")"
cat > "${compose_tmp}" <<COMPOSE
services:
  report:
    image: ${image}
    container_name: ${container_name}
    restart: unless-stopped
    read_only: true
    ports:
      - "127.0.0.1:${port}:80"
    tmpfs:
      - /var/cache/nginx
      - /var/run
    volumes:
      - ./current:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/healthz | grep -qx ok"]
      interval: 2s
      timeout: 3s
      retries: 5
COMPOSE
mv "${compose_tmp}" "${remote_root}/compose.yml"

if [[ ! -f "${remote_root}/tls/${domain}.crt" || ! -f "${remote_root}/tls/${domain}.key" ]]; then
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "${remote_root}/tls/${domain}.key" \
    -out "${remote_root}/tls/${domain}.crt" \
    -subj "/CN=${domain}" \
    -addext "subjectAltName=DNS:${domain}" >/dev/null 2>&1
  chmod 600 "${remote_root}/tls/${domain}.key"
  chmod 644 "${remote_root}/tls/${domain}.crt"
fi

atomic_current "${remote_release}"
switched=1
docker compose -f "${remote_root}/compose.yml" up -d --force-recreate
wait_healthy "${container_name}"
curl -fsS --max-time 10 "http://127.0.0.1:${port}/healthz" | grep -qx ok

site_tmp="$(mktemp)"
cat > "${site_tmp}" <<'HOST_NGINX'
# managed-by: llm-abm-marketing-sim deploy_abm_report.sh
server {
    listen 80;
    listen [::]:80;
    server_name __DOMAIN__;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name __DOMAIN__;
    ssl_certificate __REMOTE_ROOT__/tls/__DOMAIN__.crt;
    ssl_certificate_key __REMOTE_ROOT__/tls/__DOMAIN__.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_timeout 1d;
    ssl_session_cache shared:abm_report_ssl:10m;
    location / {
        proxy_pass http://127.0.0.1:__PORT__;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
HOST_NGINX
sed \
  -e "s|__DOMAIN__|${domain}|g" \
  -e "s|__REMOTE_ROOT__|${remote_root}|g" \
  -e "s|__PORT__|${port}|g" \
  "${site_tmp}" > "${site_available}"
site_written=1
rm -f "${site_tmp}"
ln -sfn "${site_available}" "${site_enabled}"
nginx -t
systemctl reload nginx

trap - EXIT
docker rm -f "${candidate_name}" >/dev/null 2>&1 || true
[[ -z "${site_backup}" ]] || rm -f "${site_backup}"
printf 'Remote candidate, container, and Nginx checks passed\n'
REMOTE_DEPLOY

cutover_complete=1
rollback_remote() {
  ssh "${DEPLOY_HOST}" bash -s -- \
    "${REMOTE_ROOT}" "${PREVIOUS_RELEASE}" "${CONTAINER_NAME}" <<'REMOTE_ROLLBACK'
set -euo pipefail
remote_root="$1"
previous_release="$2"
container_name="$3"
if [[ -n "${previous_release}" ]]; then
  previous_report_sha="$(sha256sum "${previous_release}/report.html" | awk '{print $1}')"
  sed -i \
    "s/X-Artifact-SHA256 \"[a-f0-9]\\{64\\}\"/X-Artifact-SHA256 \"${previous_report_sha}\"/" \
    "${remote_root}/nginx/default.conf"
  temporary_link="${remote_root}/.current.rollback.$$.tmp"
  ln -s "${previous_release}" "${temporary_link}"
  mv -Tf "${temporary_link}" "${remote_root}/current"
  docker compose -f "${remote_root}/compose.yml" up -d --force-recreate
  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${container_name}" 2>/dev/null || true)"
    [[ "${health}" == "healthy" ]] && exit 0
    sleep 2
  done
  exit 1
fi
docker compose -f "${remote_root}/compose.yml" down
rm -f "${remote_root}/current"
REMOTE_ROLLBACK
}

rollback_on_failure() {
  status="${1:-$?}"
  trap - EXIT
  if (( status != 0 && cutover_complete == 1 )); then
    printf 'Public acceptance failed; restoring previous release %s\n' "${PREVIOUS_RELEASE:-<none>}" >&2
    rollback_remote || printf 'deploy error: automatic rollback failed\n' >&2
  fi
  if ! cleanup_local_snapshot && (( status == 0 )); then
    status=1
  fi
  exit "${status}"
}
trap rollback_on_failure EXIT

for _attempt in 1 2 3 4 5 6 7 8; do
  if curl -fsS --max-time 20 "https://${DOMAIN}/healthz" >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS --max-time 20 "https://${DOMAIN}/healthz" >/dev/null || fail "public health check failed"

PUBLIC_REPORT_HEADERS="$(curl -fsSIL --max-time 30 \
  -H 'Cache-Control: no-cache' \
  "https://${DOMAIN}/report.html?release=${RELEASE_ID}")"
REMOTE_REPORT_HEADER_SHA="$(printf '%s\n' "${PUBLIC_REPORT_HEADERS}" \
  | awk 'tolower($1) == "x-artifact-sha256:" {gsub("\\r", "", $2); print $2}' \
  | tail -n 1)"
[[ "${REMOTE_REPORT_HEADER_SHA}" == "${LOCAL_REPORT_SHA}" ]] || fail "public report checksum header mismatch"

PUBLIC_MANIFEST="$(mktemp)"
PUBLIC_REPORT="$(mktemp)"
cleanup_public_artifacts() {
  rm -f "${PUBLIC_MANIFEST}" "${PUBLIC_REPORT}"
}
cleanup_and_rollback_on_failure() {
  status=$?
  cleanup_public_artifacts
  rollback_on_failure "${status}"
}
trap cleanup_and_rollback_on_failure EXIT
curl -fsSL --compressed --max-time 180 \
  -H 'Cache-Control: no-cache' \
  "https://${DOMAIN}/report.html?release=${RELEASE_ID}" \
  -o "${PUBLIC_REPORT}"
REMOTE_REPORT_SHA="$(shasum -a 256 "${PUBLIC_REPORT}" | awk '{print $1}')"
[[ "${REMOTE_REPORT_SHA}" == "${LOCAL_REPORT_SHA}" ]] || fail "public report checksum mismatch"

curl -fsSL --max-time 30 \
  -H 'Cache-Control: no-cache' \
  "https://${DOMAIN}/artifact_manifest.json?release=${RELEASE_ID}" \
  -o "${PUBLIC_MANIFEST}"
REMOTE_MANIFEST_SHA="$(shasum -a 256 "${PUBLIC_MANIFEST}" | awk '{print $1}')"
[[ "${REMOTE_MANIFEST_SHA}" == "${LOCAL_MANIFEST_SHA}" ]] || fail "public manifest checksum mismatch"

for artifact in \
  artifact_manifest.json \
  final_research_report_payload.json \
  final_research_users.csv \
  seed_first_sample_audit.json \
  field_lineage_catalog.json \
  user_field_trace.json; do
  curl -fsSIL --max-time 30 "https://${DOMAIN}/${artifact}" >/dev/null || \
    fail "public artifact check failed: ${artifact}"
done

ABM_DEPLOY_PUBLIC_URL="https://${DOMAIN}" \
  npx playwright test tests/playwright/deployed-abm-report.spec.ts

cleanup_public_artifacts
cleanup_local_snapshot
trap - EXIT
printf 'Deployment complete\n'
printf 'Report: https://%s/\n' "${DOMAIN}"
printf 'Network feedback: https://%s/#network-feedback\n' "${DOMAIN}"
printf 'Release: %s\n' "${RELEASE_ID}"
printf 'Report SHA-256: %s\n' "${LOCAL_REPORT_SHA}"
