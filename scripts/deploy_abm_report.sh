#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SOURCE_DIR="${ABM_REPORT_SOURCE_DIR:-${REPO_ROOT}/runs/jinjiang-prompt-v2-final-research-20260714T180251Z}"
DEPLOY_HOST="${ABM_DEPLOY_HOST:-q1ngyuan.top}"
DOMAIN="${ABM_DEPLOY_DOMAIN:-abm.q1ngyuan.top}"
REMOTE_ROOT="${ABM_DEPLOY_REMOTE_ROOT:-/opt/llm-abm-marketing-sim-report}"
PORT="${ABM_DEPLOY_PORT:-18083}"
CONTAINER_NAME="${ABM_DEPLOY_CONTAINER_NAME:-abm-research-report}"
IMAGE="${ABM_DEPLOY_IMAGE:-nginx:1.27-alpine}"
RELEASE_ID="${ABM_DEPLOY_RELEASE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

fail() {
  printf 'deploy error: %s\n' "$*" >&2
  exit 1
}

[[ -d "${SOURCE_DIR}" ]] || fail "source directory does not exist: ${SOURCE_DIR}"
for required in report.html artifact_manifest.json final_research_report_payload.json final_research_users.csv final_research_users.json; do
  [[ -f "${SOURCE_DIR}/${required}" ]] || fail "missing required artifact: ${required}"
done

if find "${SOURCE_DIR}" -type l -print -quit | grep -q .; then
  fail "source directory must not contain symlinks"
fi

[[ "${DOMAIN}" =~ ^[A-Za-z0-9.-]+$ ]] || fail "invalid domain: ${DOMAIN}"
[[ "${PORT}" =~ ^[0-9]+$ ]] || fail "invalid port: ${PORT}"
(( PORT >= 1024 && PORT <= 65535 )) || fail "port must be between 1024 and 65535"
[[ "${REMOTE_ROOT}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "invalid remote root: ${REMOTE_ROOT}"
[[ "${CONTAINER_NAME}" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "invalid container name: ${CONTAINER_NAME}"
[[ "${IMAGE}" =~ ^[A-Za-z0-9._/:@-]+$ ]] || fail "invalid image reference: ${IMAGE}"
[[ "${RELEASE_ID}" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "invalid release id: ${RELEASE_ID}"

LOCAL_REPORT_SHA="$(shasum -a 256 "${SOURCE_DIR}/report.html" | awk '{print $1}')"
REMOTE_RELEASE="${REMOTE_ROOT}/releases/${RELEASE_ID}"

printf 'Uploading %s to %s:%s\n' "${SOURCE_DIR}" "${DEPLOY_HOST}" "${REMOTE_RELEASE}"
ssh "${DEPLOY_HOST}" "install -d -m 755 '${REMOTE_RELEASE}'"
COPYFILE_DISABLE=1 tar --no-xattrs -C "${SOURCE_DIR}" -czf - . \
  | ssh "${DEPLOY_HOST}" "tar -xzf - -C '${REMOTE_RELEASE}'"

ssh "${DEPLOY_HOST}" bash -s -- \
  "${REMOTE_ROOT}" \
  "${REMOTE_RELEASE}" \
  "${DOMAIN}" \
  "${PORT}" \
  "${CONTAINER_NAME}" \
  "${IMAGE}" <<'REMOTE_SCRIPT'
set -euo pipefail

remote_root="$1"
remote_release="$2"
domain="$3"
port="$4"
container_name="$5"
image="$6"

managed_marker="# managed-by: llm-abm-marketing-sim deploy_abm_report.sh"
site_available="/etc/nginx/sites-available/${domain}"
site_enabled="/etc/nginx/sites-enabled/${domain}"

if [[ -e "${site_available}" ]] && ! grep -Fq "${managed_marker}" "${site_available}"; then
  printf 'deploy error: refusing to overwrite unmanaged nginx site %s\n' "${site_available}" >&2
  exit 1
fi

install -d -m 755 "${remote_root}/nginx" "${remote_root}/tls" "${remote_root}/releases"
find "${remote_release}" -type d -exec chmod 755 {} +
find "${remote_release}" -type f -exec chmod 644 {} +
ln -sfn "${remote_release}" "${remote_root}/current"

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

    location = / {
        try_files /report.html =404;
    }

    location = /report.html {
        try_files $uri =404;
    }

    location ~* \.csv$ {
        default_type text/csv;
        charset utf-8;
        try_files $uri =404;
    }

    location / {
        try_files $uri =404;
    }
}
CONTAINER_NGINX

cat > "${remote_root}/compose.yml" <<COMPOSE
services:
  report:
    image: ${image}
    container_name: ${container_name}
    restart: unless-stopped
    ports:
      - "127.0.0.1:${port}:80"
    volumes:
      - ./current:/usr/share/nginx/html:ro
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/healthz | grep -qx ok"]
      interval: 10s
      timeout: 3s
      retries: 5
COMPOSE

if [[ ! -f "${remote_root}/tls/${domain}.crt" || ! -f "${remote_root}/tls/${domain}.key" ]]; then
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "${remote_root}/tls/${domain}.key" \
    -out "${remote_root}/tls/${domain}.crt" \
    -subj "/CN=${domain}" \
    -addext "subjectAltName=DNS:${domain}" >/dev/null 2>&1
  chmod 600 "${remote_root}/tls/${domain}.key"
  chmod 644 "${remote_root}/tls/${domain}.crt"
fi

docker compose -f "${remote_root}/compose.yml" up -d --force-recreate

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
rm "${site_tmp}"
ln -sfn "${site_available}" "${site_enabled}"

nginx -t
systemctl reload nginx

for attempt in 1 2 3 4 5 6; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${container_name}")"
  [[ "${health}" == "healthy" ]] && break
  sleep 2
done

[[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${container_name}")" == "healthy" ]] || {
  docker logs --tail 80 "${container_name}" >&2
  exit 1
}
REMOTE_SCRIPT

for attempt in 1 2 3 4 5 6 7 8; do
  if curl -fsS --max-time 20 "https://${DOMAIN}/healthz" >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS --max-time 20 "https://${DOMAIN}/healthz" >/dev/null || fail "public health check failed"
REMOTE_REPORT_SHA="$(curl -fsSL --max-time 60 -H 'Accept-Encoding: identity' -H 'Cache-Control: no-cache' "https://${DOMAIN}/report.html?release=${RELEASE_ID}" | shasum -a 256 | awk '{print $1}')"
[[ "${REMOTE_REPORT_SHA}" == "${LOCAL_REPORT_SHA}" ]] || fail "public report checksum mismatch"

for artifact in artifact_manifest.json final_research_report_payload.json final_research_users.csv final_research_users.json; do
  curl -fsSIL --max-time 20 "https://${DOMAIN}/${artifact}" >/dev/null || fail "public artifact check failed: ${artifact}"
done

printf 'Deployment complete\n'
printf 'Report: https://%s/\n' "${DOMAIN}"
printf 'Network feedback: https://%s/#network-feedback\n' "${DOMAIN}"
printf 'Release: %s\n' "${RELEASE_ID}"
printf 'Report SHA-256: %s\n' "${LOCAL_REPORT_SHA}"
