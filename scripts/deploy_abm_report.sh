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
DEPLOYMENT_FACTS_FILE=""
LOCAL_CHECKSUMS_FILE=""

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
  local cleanup_status=0
  [[ -z "${DEPLOYMENT_FACTS_FILE}" ]] || rm -f -- "${DEPLOYMENT_FACTS_FILE}" || cleanup_status=1
  [[ -z "${LOCAL_CHECKSUMS_FILE}" ]] || rm -f -- "${LOCAL_CHECKSUMS_FILE}" || cleanup_status=1
  DEPLOYMENT_FACTS_FILE=""
  LOCAL_CHECKSUMS_FILE=""
  if [[ -n "${snapshot_dir}" && -d "${snapshot_dir}" ]]; then
    if command -v chflags >/dev/null 2>&1; then
      chflags -R nouchg,noschg "${snapshot_dir}" 2>/dev/null || true
    fi
    chmod -R u+w "${snapshot_dir}" 2>/dev/null || true
    if ! rm -r -- "${snapshot_dir}"; then
      printf 'deploy error: cannot remove local release snapshot %s\n' "${snapshot_dir}" >&2
      cleanup_status=1
    fi
  fi
  LOCAL_SNAPSHOT_DIR=""
  return "${cleanup_status}"
}
LOCAL_SNAPSHOT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/abm-report-deploy.XXXXXX")"
DEPLOYMENT_FACTS_FILE="$(mktemp "${TMPDIR:-/tmp}/abm-report-deployment-facts.XXXXXX")"
LOCAL_CHECKSUMS_FILE="$(mktemp "${TMPDIR:-/tmp}/abm-report-deployment-checksums.XXXXXX")"
trap cleanup_local_snapshot EXIT
LOCAL_SNAPSHOT_DIR="$(cd -- "${LOCAL_SNAPSHOT_DIR}" && pwd -P)" || fail "cannot resolve local release snapshot"
DEPLOYMENT_FACTS_FILE="$(cd -- "$(dirname -- "${DEPLOYMENT_FACTS_FILE}")" && printf '%s/%s\n' "$(pwd -P)" "$(basename -- "${DEPLOYMENT_FACTS_FILE}")")" || fail "cannot resolve deployment facts path"
LOCAL_CHECKSUMS_FILE="$(cd -- "$(dirname -- "${LOCAL_CHECKSUMS_FILE}")" && printf '%s/%s\n' "$(pwd -P)" "$(basename -- "${LOCAL_CHECKSUMS_FILE}")")" || fail "cannot resolve deployment checksums path"
COPYFILE_DISABLE=1 cp -R "${CANONICAL_SOURCE_DIR}/." "${LOCAL_SNAPSHOT_DIR}/"

"${PYTHON}" "${SCRIPT_DIR}/validate_abm_report_release.py" \
  --repo-root "${REPO_ROOT}" \
  --contract "${RELEASE_CONTRACT}" \
  --source-dir "${SOURCE_DIR}" \
  --snapshot-dir "${LOCAL_SNAPSHOT_DIR}" \
  --require-formal-production \
  --deployment-facts-output "${DEPLOYMENT_FACTS_FILE}" \
  --deployment-release-id "${RELEASE_ID}" \
  --deployment-domain "${DOMAIN}"

deployment_fact() {
  "${PYTHON}" - "${DEPLOYMENT_FACTS_FILE}" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    facts = json.load(stream)
value = facts.get(sys.argv[2])
if not isinstance(value, (str, int)) or isinstance(value, bool):
    raise SystemExit(f"deployment fact is missing or invalid: {sys.argv[2]}")
print(value)
PY
}

VALIDATED_RELEASE_ID="$(deployment_fact release_id)" || fail "cannot read validated release id"
VALIDATED_DOMAIN="$(deployment_fact canonical_domain)" || fail "cannot read validated canonical domain"
PUBLIC_ACCEPTANCE_REPORT_KIND="$(deployment_fact report_kind)" || fail "cannot read validated report kind"
RELEASE_CONTRACT_SCHEMA="$(deployment_fact release_contract_schema_version)" || fail "cannot read validated release contract schema"
CONTRACT_SHA="$(deployment_fact contract_sha256)" || fail "cannot read validated contract identity"
RELEASE_IDENTITY_SHA="$(deployment_fact release_identity_sha256)" || fail "cannot read validated release identity"
LOCAL_REPORT_SHA="$(deployment_fact report_sha256)" || fail "cannot read validated report hash"
LOCAL_MANIFEST_SHA="$(deployment_fact manifest_sha256)" || fail "cannot read validated manifest hash"
ARTIFACT_COUNT="$("${PYTHON}" - "${DEPLOYMENT_FACTS_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    facts = json.load(stream)
print(len(facts["artifact_sha256"]))
PY
)" || fail "cannot read validated artifact count"
PUBLIC_ACCEPTANCE_ARTIFACTS_JSON="$("${PYTHON}" - "${DEPLOYMENT_FACTS_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    facts = json.load(stream)
print(json.dumps(facts["public_acceptance_artifacts"], ensure_ascii=False, separators=(",", ":")))
PY
)" || fail "cannot read validated public acceptance artifacts"
ARTIFACT_CHECKSUMS_B64="$("${PYTHON}" - "${DEPLOYMENT_FACTS_FILE}" "${LOCAL_CHECKSUMS_FILE}" <<'PY'
import base64
import json
import sys
from pathlib import Path

with open(sys.argv[1], encoding="utf-8") as stream:
    facts = json.load(stream)
rows = "".join(
    f"{digest}  {path}\n"
    for path, digest in sorted(facts["artifact_sha256"].items())
)
payload = rows.encode("ascii")
Path(sys.argv[2]).write_bytes(payload)
print(base64.b64encode(payload).decode("ascii"))
PY
)" || fail "cannot materialize validated artifact checksums"
[[ "${VALIDATED_RELEASE_ID}" == "${RELEASE_ID}" ]] || fail "validated release id is crossed"
[[ "${VALIDATED_DOMAIN}" == "${DOMAIN}" ]] || fail "validated canonical domain is crossed"
[[ "${ARTIFACT_COUNT}" =~ ^[1-9][0-9]*$ ]] || fail "validated artifact count is invalid"
[[ "${CONTRACT_SHA}" =~ ^[a-f0-9]{64}$ ]] || fail "validated contract identity is invalid"
[[ "${RELEASE_CONTRACT_SCHEMA}" =~ ^abm-report-release-contract-v[2-9]$ ]] || fail "validated release contract schema is invalid"
[[ -z "${RELEASE_IDENTITY_SHA}" || "${RELEASE_IDENTITY_SHA}" =~ ^[a-f0-9]{64}$ ]] || fail "validated release identity is invalid"
SOURCE_DIR="${LOCAL_SNAPSHOT_DIR}"
find "${SOURCE_DIR}" -type d -exec chmod a-w {} +
find "${SOURCE_DIR}" -type f -exec chmod a-w {} +
(
  cd -- "${SOURCE_DIR}"
  shasum -a 256 -c "${LOCAL_CHECKSUMS_FILE}" >/dev/null
) || fail "physical snapshot inventory or hashes changed after validation"
ACTUAL_SNAPSHOT_FILES="$(find "${SOURCE_DIR}" -type f | wc -l | tr -d '[:space:]')"
[[ "${ACTUAL_SNAPSHOT_FILES}" == "${ARTIFACT_COUNT}" ]] || fail "physical snapshot file inventory changed after validation"
PUBLIC_ACCEPTANCE_ARTIFACTS=()
while IFS= read -r artifact; do
  [[ -n "${artifact}" ]] || continue
  PUBLIC_ACCEPTANCE_ARTIFACTS+=("${artifact}")
done < <("${PYTHON}" - "${DEPLOYMENT_FACTS_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    facts = json.load(stream)
for artifact in facts["public_acceptance_artifacts"]:
    print(artifact)
PY
)
(( ${#PUBLIC_ACCEPTANCE_ARTIFACTS[@]} == ARTIFACT_COUNT )) || fail "validated public acceptance artifact list is incomplete"
REMOTE_RELEASE="${REMOTE_ROOT}/releases/${RELEASE_ID}"

PREVIOUS_RELEASE_FILE="$(mktemp "${TMPDIR:-/tmp}/abm-report-previous-release.XXXXXX")"
if ssh "${DEPLOY_HOST}" bash -s -- "${REMOTE_ROOT}" > "${PREVIOUS_RELEASE_FILE}" <<'READ_CURRENT'
set -euo pipefail
remote_root="$1"
current="${remote_root}/current"
[[ -L "${current}" ]] || exit 0
previous="$(readlink -f "${current}")"
case "${previous}" in
  "${remote_root}"/releases/*) ;;
  *) printf 'deploy error: current points outside managed releases: %s\n' "${previous}" >&2; exit 1 ;;
esac
[[ -f "${previous}/report.html" && ! -L "${previous}/report.html" ]] || {
  printf 'deploy error: current release report is missing or unsafe\n' >&2
  exit 1
}
[[ -f "${previous}/artifact_manifest.json" && ! -L "${previous}/artifact_manifest.json" ]] || {
  printf 'deploy error: current release manifest is missing or unsafe\n' >&2
  exit 1
}
previous_report_sha="$(sha256sum "${previous}/report.html" | awk '{print $1}')"
previous_manifest_sha="$(sha256sum "${previous}/artifact_manifest.json" | awk '{print $1}')"
printf '%s\t%s\t%s\n' "${previous}" "${previous_report_sha}" "${previous_manifest_sha}"
READ_CURRENT
then
  :
else
  rm -f "${PREVIOUS_RELEASE_FILE}"
  fail "cannot read current managed release"
fi
PREVIOUS_RELEASE_RECORD="$(<"${PREVIOUS_RELEASE_FILE}")"
rm -f "${PREVIOUS_RELEASE_FILE}"
PREVIOUS_RELEASE=""
PREVIOUS_REPORT_SHA=""
PREVIOUS_MANIFEST_SHA=""
if [[ -n "${PREVIOUS_RELEASE_RECORD}" ]]; then
  IFS=$'\t' read -r PREVIOUS_RELEASE PREVIOUS_REPORT_SHA PREVIOUS_MANIFEST_SHA <<< "${PREVIOUS_RELEASE_RECORD}"
  [[ -n "${PREVIOUS_RELEASE}" && "${PREVIOUS_REPORT_SHA}" =~ ^[a-f0-9]{64}$ && "${PREVIOUS_MANIFEST_SHA}" =~ ^[a-f0-9]{64}$ ]] || \
    fail "current managed release identity is incomplete"
fi
PREVIOUS_RELEASE_ARG="${PREVIOUS_RELEASE:-__ABM_NO_PREVIOUS_RELEASE__}"
PREVIOUS_REPORT_SHA_ARG="${PREVIOUS_REPORT_SHA:-__ABM_NO_PREVIOUS_REPORT_SHA__}"
PREVIOUS_MANIFEST_SHA_ARG="${PREVIOUS_MANIFEST_SHA:-__ABM_NO_PREVIOUS_MANIFEST_SHA__}"

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
  "${PREVIOUS_RELEASE_ARG}" \
  "${PREVIOUS_REPORT_SHA_ARG}" \
  "${PREVIOUS_MANIFEST_SHA_ARG}" \
  "${DOMAIN}" \
  "${PORT}" \
  "${CONTAINER_NAME}" \
  "${IMAGE}" \
  "${LOCAL_REPORT_SHA}" \
  "${LOCAL_MANIFEST_SHA}" \
  "${RELEASE_ID}" \
  "${RELEASE_IDENTITY_SHA}" \
  "${CONTRACT_SHA}" \
  "${ARTIFACT_CHECKSUMS_B64}" \
  "${ARTIFACT_COUNT}" \
  "${RELEASE_CONTRACT_SCHEMA}" <<'REMOTE_DEPLOY'
set -euo pipefail

remote_root="$1"
remote_release="$2"
previous_release="$3"
[[ "${previous_release}" != "__ABM_NO_PREVIOUS_RELEASE__" ]] || previous_release=""
previous_report_sha="$4"
[[ "${previous_report_sha}" != "__ABM_NO_PREVIOUS_REPORT_SHA__" ]] || previous_report_sha=""
previous_manifest_sha="$5"
[[ "${previous_manifest_sha}" != "__ABM_NO_PREVIOUS_MANIFEST_SHA__" ]] || previous_manifest_sha=""
domain="$6"
port="$7"
container_name="$8"
image="$9"
report_sha="${10}"
manifest_sha="${11}"
release_id="${12}"
release_identity_sha="${13}"
validated_contract_sha="${14}"
artifact_checksums_b64="${15}"
artifact_count="${16}"
release_contract_schema="${17}"

managed_marker="# managed-by: llm-abm-marketing-sim deploy_abm_report.sh"
site_available="/etc/nginx/sites-available/${domain}"
site_enabled="/etc/nginx/sites-enabled/${domain}"
candidate_name="${container_name}-candidate"
site_backup=""
site_existed=0
site_written=0
switched=0
contract_checksums=""

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

validate_previous_identity() {
  context="$1"
  current="${remote_root}/current"
  if [[ -n "${previous_release}" ]]; then
    [[ -L "${current}" && "$(readlink -f "${current}")" == "${previous_release}" ]] || {
      printf 'deploy error: current changed during %s\n' "${context}" >&2
      return 1
    }
    [[ "$(sha256sum "${previous_release}/report.html" | awk '{print $1}')" == "${previous_report_sha}" ]] || {
      printf 'deploy error: rollback report identity changed during %s\n' "${context}" >&2
      return 1
    }
    [[ "$(sha256sum "${previous_release}/artifact_manifest.json" | awk '{print $1}')" == "${previous_manifest_sha}" ]] || {
      printf 'deploy error: rollback manifest identity changed during %s\n' "${context}" >&2
      return 1
    }
  elif [[ -e "${current}" || -L "${current}" ]]; then
    printf 'deploy error: current appeared during %s\n' "${context}" >&2
    return 1
  fi
}

rollback() {
  set +e
  rollback_status=0
  if [[ -n "${previous_release}" ]]; then
    sed -i \
      "s/X-Artifact-SHA256 \"[a-f0-9]\\{64\\}\"/X-Artifact-SHA256 \"${previous_report_sha}\"/" \
      "${remote_root}/nginx/default.conf" || rollback_status=1
  fi
  if (( switched == 1 )); then
    if [[ -n "${previous_release}" ]]; then
      atomic_current "${previous_release}" || rollback_status=1
      docker compose -f "${remote_root}/compose.yml" up -d --force-recreate || rollback_status=1
      wait_healthy "${container_name}" || rollback_status=1
    else
      docker compose -f "${remote_root}/compose.yml" down || rollback_status=1
      rm -f "${remote_root}/current" || rollback_status=1
    fi
  fi
  if [[ -n "${site_backup}" && -f "${site_backup}" ]]; then
    install -m 644 "${site_backup}" "${site_available}" || rollback_status=1
  elif (( site_written == 1 && site_existed == 0 )); then
    rm -f "${site_enabled}" "${site_available}" || rollback_status=1
  fi
  nginx -t && systemctl reload nginx || rollback_status=1
  validate_previous_identity "rollback restoration" || rollback_status=1
  if [[ -n "${previous_release}" && "${rollback_status}" == "0" ]]; then
    restored_report_sha="$(docker exec "${container_name}" wget -qO- http://127.0.0.1/report.html | sha256sum | awk '{print $1}')"
    restored_manifest_sha="$(docker exec "${container_name}" wget -qO- http://127.0.0.1/artifact_manifest.json | sha256sum | awk '{print $1}')"
    [[ "${restored_report_sha}" == "${previous_report_sha}" && "${restored_manifest_sha}" == "${previous_manifest_sha}" ]] || rollback_status=1
  fi
  return "${rollback_status}"
}

finish() {
  status=$?
  trap - EXIT
  docker rm -f "${candidate_name}" >/dev/null 2>&1 || true
  [[ -z "${contract_checksums}" ]] || rm -f "${contract_checksums}"
  if (( status != 0 )); then
    rollback || printf 'deploy error: remote rollback identity verification failed\n' >&2
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
[[ "${report_sha}" =~ ^[a-f0-9]{64}$ && "${manifest_sha}" =~ ^[a-f0-9]{64}$ ]] || {
  printf 'deploy error: invalid approved report or manifest SHA-256\n' >&2
  exit 1
}
[[ "${validated_contract_sha}" =~ ^[a-f0-9]{64}$ ]] || {
  printf 'deploy error: invalid validated contract identity\n' >&2
  exit 1
}
[[ "${release_contract_schema}" =~ ^abm-report-release-contract-v[2-9]$ ]] || {
  printf 'deploy error: invalid validated release contract schema\n' >&2
  exit 1
}
[[ "${artifact_count}" =~ ^[1-9][0-9]*$ ]] || {
  printf 'deploy error: invalid validated artifact count\n' >&2
  exit 1
}
[[ "${remote_release}" == "${remote_root}/releases/${release_id}" ]] || {
  printf 'deploy error: remote release path is crossed with the validated release id\n' >&2
  exit 1
}
find "${remote_release}" -type l -print -quit | grep -q . && {
  printf 'deploy error: uploaded release contains a symlink\n' >&2
  exit 1
}
find "${remote_release}" ! -type d ! -type f -print -quit | grep -q . && {
  printf 'deploy error: uploaded release contains a non-regular entry\n' >&2
  exit 1
}
contract_checksums="$(mktemp)"
printf '%s' "${artifact_checksums_b64}" | base64 --decode > "${contract_checksums}"
[[ "$(wc -l < "${contract_checksums}" | tr -d '[:space:]')" == "${artifact_count}" ]] || {
  printf 'deploy error: validated contract checksum inventory is incomplete\n' >&2
  exit 1
}
while IFS= read -r checksum_row; do
  digest="${checksum_row%%  *}"
  relative_path="${checksum_row#*  }"
  [[ "${digest}" =~ ^[a-f0-9]{64}$ && "${relative_path}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || {
    printf 'deploy error: invalid validated contract checksum row\n' >&2
    exit 1
  }
  case "/${relative_path}/" in
    *'/../'*|*'/./'*) printf 'deploy error: validated artifact path escapes release\n' >&2; exit 1 ;;
  esac
  [[ -f "${remote_release}/${relative_path}" && ! -L "${remote_release}/${relative_path}" ]] || {
    printf 'deploy error: validated remote artifact is missing: %s\n' "${relative_path}" >&2
    exit 1
  }
done < "${contract_checksums}"
[[ "$(find "${remote_release}" -type f | wc -l | tr -d '[:space:]')" == "${artifact_count}" ]] || {
  printf 'deploy error: remote release has missing or extra files\n' >&2
  exit 1
}
(
  cd "${remote_release}"
  sha256sum -c "${contract_checksums}" >/dev/null
) || {
  printf 'deploy error: remote release differs from the validated contract inventory\n' >&2
  exit 1
}
find "${remote_release}" -type d -exec chmod 755 {} +
find "${remote_release}" -type f -exec chmod 644 {} +
uploaded_report_sha="$(sha256sum "${remote_release}/report.html" | awk '{print $1}')"
uploaded_manifest_sha="$(sha256sum "${remote_release}/artifact_manifest.json" | awk '{print $1}')"
[[ "${uploaded_report_sha}" == "${report_sha}" && "${uploaded_manifest_sha}" == "${manifest_sha}" ]] || {
  printf 'deploy error: uploaded report or manifest checksum mismatch\n' >&2
  exit 1
}
if [[ -n "${release_identity_sha}" ]]; then
  [[ "${release_identity_sha}" =~ ^[a-f0-9]{64}$ ]] || {
    printf 'deploy error: invalid validated release identity\n' >&2
    exit 1
  }
  grep -Fq "<meta name=\"abm-release-id\" content=\"${release_id}\">" "${remote_release}/report.html" || {
    printf 'deploy error: remote report release id is crossed\n' >&2
    exit 1
  }
  grep -Fq "<meta name=\"abm-release-contract\" content=\"${release_contract_schema}\">" "${remote_release}/report.html" || {
    printf 'deploy error: remote report release contract is crossed\n' >&2
    exit 1
  }
  grep -Fq "\"release_id\":\"${release_id}\"" "${remote_release}/artifact_manifest.json" || {
    printf 'deploy error: remote manifest release id is crossed\n' >&2
    exit 1
  }
  grep -Fq "\"release_identity_sha256\":\"${release_identity_sha}\"" "${remote_release}/artifact_manifest.json" || {
    printf 'deploy error: remote manifest release identity is crossed\n' >&2
    exit 1
  }
fi
validate_previous_identity "before candidate health"

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
        add_header Cache-Control "no-cache, no-transform" always;
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
docker exec "${candidate_name}" test -f /usr/share/nginx/html/artifact_manifest.json
candidate_report_sha="$(docker exec "${candidate_name}" wget -qO- http://127.0.0.1/report.html | sha256sum | awk '{print $1}')"
candidate_manifest_sha="$(docker exec "${candidate_name}" wget -qO- http://127.0.0.1/artifact_manifest.json | sha256sum | awk '{print $1}')"
[[ "${candidate_report_sha}" == "${report_sha}" && "${candidate_manifest_sha}" == "${manifest_sha}" ]] || {
  printf 'deploy error: candidate Nginx report or manifest identity is crossed\n' >&2
  exit 1
}
while IFS= read -r checksum_row; do
  relative_path="${checksum_row#*  }"
  docker exec "${candidate_name}" test -f "/usr/share/nginx/html/${relative_path}" || {
    printf 'deploy error: candidate container inventory is incomplete: %s\n' "${relative_path}" >&2
    exit 1
  }
done < "${contract_checksums}"

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
validate_previous_identity "before atomic current switch"

atomic_current "${remote_release}"
switched=1
docker compose -f "${remote_root}/compose.yml" up -d --force-recreate
wait_healthy "${container_name}"
curl -fsS --max-time 10 "http://127.0.0.1:${port}/healthz" | grep -qx ok
systemctl reload nginx

trap - EXIT
docker rm -f "${candidate_name}" >/dev/null 2>&1 || true
[[ -z "${contract_checksums}" ]] || rm -f "${contract_checksums}"
[[ -z "${site_backup}" ]] || rm -f "${site_backup}"
printf 'Remote candidate, container, and Nginx checks passed\n'
REMOTE_DEPLOY

cutover_complete=1
rollback_remote() {
  ssh "${DEPLOY_HOST}" bash -s -- \
    "${REMOTE_ROOT}" \
    "${PREVIOUS_RELEASE_ARG}" \
    "${PREVIOUS_REPORT_SHA_ARG}" \
    "${PREVIOUS_MANIFEST_SHA_ARG}" \
    "${CONTAINER_NAME}" <<'REMOTE_ROLLBACK'
set -euo pipefail
remote_root="$1"
previous_release="$2"
[[ "${previous_release}" != "__ABM_NO_PREVIOUS_RELEASE__" ]] || previous_release=""
previous_report_sha="$3"
[[ "${previous_report_sha}" != "__ABM_NO_PREVIOUS_REPORT_SHA__" ]] || previous_report_sha=""
previous_manifest_sha="$4"
[[ "${previous_manifest_sha}" != "__ABM_NO_PREVIOUS_MANIFEST_SHA__" ]] || previous_manifest_sha=""
container_name="$5"
if [[ -n "${previous_release}" ]]; then
  [[ "${previous_report_sha}" =~ ^[a-f0-9]{64}$ && "${previous_manifest_sha}" =~ ^[a-f0-9]{64}$ ]] || exit 1
  [[ "$(sha256sum "${previous_release}/report.html" | awk '{print $1}')" == "${previous_report_sha}" ]] || exit 1
  [[ "$(sha256sum "${previous_release}/artifact_manifest.json" | awk '{print $1}')" == "${previous_manifest_sha}" ]] || exit 1
  sed -i \
    "s/X-Artifact-SHA256 \"[a-f0-9]\\{64\\}\"/X-Artifact-SHA256 \"${previous_report_sha}\"/" \
    "${remote_root}/nginx/default.conf"
  temporary_link="${remote_root}/.current.rollback.$$.tmp"
  ln -s "${previous_release}" "${temporary_link}"
  mv -Tf "${temporary_link}" "${remote_root}/current"
  docker compose -f "${remote_root}/compose.yml" up -d --force-recreate
  restored_health=""
  for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    restored_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${container_name}" 2>/dev/null || true)"
    [[ "${restored_health}" == "healthy" ]] && break
    sleep 2
  done
  [[ "${restored_health}" == "healthy" ]] || exit 1
  [[ "$(readlink -f "${remote_root}/current")" == "${previous_release}" ]] || exit 1
  restored_report_sha="$(docker exec "${container_name}" wget -qO- http://127.0.0.1/report.html | sha256sum | awk '{print $1}')"
  restored_manifest_sha="$(docker exec "${container_name}" wget -qO- http://127.0.0.1/artifact_manifest.json | sha256sum | awk '{print $1}')"
  [[ "${restored_report_sha}" == "${previous_report_sha}" ]] || exit 1
  [[ "${restored_manifest_sha}" == "${previous_manifest_sha}" ]] || exit 1
  exit 0
fi
docker compose -f "${remote_root}/compose.yml" down
rm -f "${remote_root}/current"
[[ ! -e "${remote_root}/current" && ! -L "${remote_root}/current" ]]
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

PUBLIC_CURL_RETRY=(--retry 4 --retry-all-errors --retry-delay 2 --retry-max-time 120)
for _attempt in 1 2 3 4 5 6 7 8; do
  if curl "${PUBLIC_CURL_RETRY[@]}" -fsS --max-time 20 "https://${DOMAIN}/healthz" >/dev/null; then
    break
  fi
  sleep 2
done
curl "${PUBLIC_CURL_RETRY[@]}" -fsS --max-time 20 "https://${DOMAIN}/healthz" >/dev/null || fail "public health check failed"

PUBLIC_REPORT_HEADERS="$(curl "${PUBLIC_CURL_RETRY[@]}" -fsSIL --max-time 30 \
  -H 'Cache-Control: no-cache' \
  "https://${DOMAIN}/report.html?release=${RELEASE_ID}")"
REMOTE_REPORT_HEADER_SHA="$(printf '%s\n' "${PUBLIC_REPORT_HEADERS}" \
  | awk 'tolower($1) == "x-artifact-sha256:" {gsub("\\r", "", $2); print $2}' \
  | tail -n 1)"
[[ "${REMOTE_REPORT_HEADER_SHA}" == "${LOCAL_REPORT_SHA}" ]] || fail "public report checksum header mismatch"

PUBLIC_MANIFEST="$(mktemp "${TMPDIR:-/tmp}/abm-report-public-manifest.XXXXXX")"
PUBLIC_REPORT="$(mktemp "${TMPDIR:-/tmp}/abm-report-public-report.XXXXXX")"
PUBLIC_ARTIFACT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/abm-report-public-artifacts.XXXXXX")"
cleanup_public_artifacts() {
  rm -f "${PUBLIC_MANIFEST}" "${PUBLIC_REPORT}"
  rm -r -- "${PUBLIC_ARTIFACT_DIR}"
}
cleanup_and_rollback_on_failure() {
  status=$?
  cleanup_public_artifacts
  rollback_on_failure "${status}"
}
trap cleanup_and_rollback_on_failure EXIT
curl "${PUBLIC_CURL_RETRY[@]}" -fsSL --compressed --max-time 180 \
  -H 'Cache-Control: no-cache' \
  "https://${DOMAIN}/report.html?release=${RELEASE_ID}" \
  -o "${PUBLIC_REPORT}"
REMOTE_REPORT_SHA="$(shasum -a 256 "${PUBLIC_REPORT}" | awk '{print $1}')"
[[ "${REMOTE_REPORT_SHA}" == "${LOCAL_REPORT_SHA}" ]] || fail "public report checksum mismatch"

curl "${PUBLIC_CURL_RETRY[@]}" -fsSL --max-time 30 \
  -H 'Cache-Control: no-cache' \
  "https://${DOMAIN}/artifact_manifest.json?release=${RELEASE_ID}" \
  -o "${PUBLIC_MANIFEST}"
REMOTE_MANIFEST_SHA="$(shasum -a 256 "${PUBLIC_MANIFEST}" | awk '{print $1}')"
[[ "${REMOTE_MANIFEST_SHA}" == "${LOCAL_MANIFEST_SHA}" ]] || fail "public manifest checksum mismatch"

for artifact in "${PUBLIC_ACCEPTANCE_ARTIFACTS[@]}"; do
  curl "${PUBLIC_CURL_RETRY[@]}" -fsSIL --max-time 30 "https://${DOMAIN}/${artifact}" >/dev/null || \
    fail "public artifact check failed: ${artifact}"
done

artifact_index=0
while IFS=$'\t' read -r artifact expected_sha; do
  [[ -n "${artifact}" && "${expected_sha}" =~ ^[a-f0-9]{64}$ ]] || fail "invalid public artifact hash contract row"
  artifact_index=$((artifact_index + 1))
  public_artifact="${PUBLIC_ARTIFACT_DIR}/artifact-${artifact_index}"
  curl "${PUBLIC_CURL_RETRY[@]}" -fsSL --compressed --max-time 180 \
    -H 'Cache-Control: no-cache' \
    "https://${DOMAIN}/${artifact}?release=${RELEASE_ID}" \
    -o "${public_artifact}"
  public_artifact_sha="$(shasum -a 256 "${public_artifact}" | awk '{print $1}')"
  [[ "${public_artifact_sha}" == "${expected_sha}" ]] || fail "public artifact checksum mismatch: ${artifact}"
done < <("${PYTHON}" - "${DEPLOYMENT_FACTS_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    facts = json.load(stream)
for artifact, digest in sorted(facts["artifact_sha256"].items()):
    print(f"{artifact}\t{digest}")
PY
)

ABM_DEPLOY_PUBLIC_URL="https://${DOMAIN}" \
ABM_DEPLOY_REPORT_KIND="${PUBLIC_ACCEPTANCE_REPORT_KIND}" \
ABM_DEPLOY_PUBLIC_ARTIFACTS="${PUBLIC_ACCEPTANCE_ARTIFACTS_JSON}" \
  npx playwright test tests/playwright/deployed-abm-report.spec.ts

cleanup_public_artifacts
cleanup_local_snapshot
trap - EXIT
DEPLOYED_AT_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
printf 'Deployment complete\n'
printf 'Deployment time (UTC): %s\n' "${DEPLOYED_AT_UTC}"
printf 'Report: https://%s/\n' "${DOMAIN}"
if [[ "${PUBLIC_ACCEPTANCE_REPORT_KIND}" == "final-research" ]]; then
  printf 'Network feedback: https://%s/#network-feedback\n' "${DOMAIN}"
fi
printf 'Release: %s\n' "${RELEASE_ID}"
printf 'Contract SHA-256: %s\n' "${CONTRACT_SHA}"
printf 'Release identity SHA-256: %s\n' "${RELEASE_IDENTITY_SHA:-<not-declared>}"
printf 'Report SHA-256: %s\n' "${LOCAL_REPORT_SHA}"
printf 'Manifest SHA-256: %s\n' "${LOCAL_MANIFEST_SHA}"
printf 'Artifact count: %s\n' "${ARTIFACT_COUNT}"
printf 'Fresh rollback release: %s\n' "${PREVIOUS_RELEASE:-<none>}"
printf 'Fresh rollback report SHA-256: %s\n' "${PREVIOUS_REPORT_SHA:-<none>}"
printf 'Fresh rollback manifest SHA-256: %s\n' "${PREVIOUS_MANIFEST_SHA:-<none>}"
printf 'Public acceptance: passed\n'
