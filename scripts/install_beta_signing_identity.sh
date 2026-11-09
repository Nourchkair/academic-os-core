#!/usr/bin/env bash
# Import Academia's stable, self-signed beta code-signing identity into a
# temporary keychain on a fresh GitHub-hosted macOS runner.
set -eo pipefail

if [ -z "${RUNNER_TEMP:-}" ] || [ -z "${GITHUB_OUTPUT:-}" ]; then
    echo "::error::RUNNER_TEMP and GITHUB_OUTPUT are required."
    exit 1
fi
if [ -z "${ACADEMIA_BETA_SIGNING_P12_B64:-}" ] || [ -z "${ACADEMIA_BETA_SIGNING_P12_PASSWORD:-}" ]; then
    echo "::error::Set ACADEMIA_BETA_SIGNING_P12_B64 and ACADEMIA_BETA_SIGNING_P12_PASSWORD in GitHub Actions secrets."
    exit 1
fi

KEYCHAIN_PATH="$RUNNER_TEMP/academia-beta-signing-$$.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -base64 32)"
P12_PATH="$RUNNER_TEMP/academia-beta-signing-$$.p12"

cleanup() {
    status=$?
    trap - EXIT
    rm -f "$P12_PATH"
    if [ "$status" -ne 0 ]; then
        security delete-keychain "$KEYCHAIN_PATH" 2>/dev/null || true
    fi
    exit "$status"
}
trap cleanup EXIT

umask 077
printf '%s' "$ACADEMIA_BETA_SIGNING_P12_B64" | base64 -D > "$P12_PATH"
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security import "$P12_PATH" -P "$ACADEMIA_BETA_SIGNING_P12_PASSWORD" \
    -A -t agg -k "$KEYCHAIN_PATH"
rm -f "$P12_PATH"
security set-key-partition-list -S "apple-tool:,apple:,codesign:" -s \
    -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH" >/dev/null

# Keep the hosted runner's existing search entries while putting the temporary
# build keychain first. Quote handling follows `security list-keychains` output.
existing=()
while IFS= read -r entry; do
    existing+=("$entry")
done < <(
    security list-keychains -d user \
        | awk -v skip="$KEYCHAIN_PATH" '
            {
                gsub(/^[[:space:]]+|[[:space:]]+$/, "")
                gsub(/^"|"$/, "")
                if ($0 != "" && $0 != skip) print
            }
        '
)
security list-keychains -d user -s "$KEYCHAIN_PATH" "${existing[@]+"${existing[@]}"}"

# Do not use `-v`: it filters out self-signed identities because they are not
# trusted by Apple, even though codesign can use the imported identity.
IDENTITY="$(security find-identity -p codesigning "$KEYCHAIN_PATH" 2>/dev/null \
    | awk '$1 ~ /^[0-9]+\)$/ && length($2) == 40 && $2 ~ /^[0-9A-Fa-f]+$/ &&
           index($0, "Academia OS Beta Release Signing") { print toupper($2); exit }')"
if [[ ! "$IDENTITY" =~ ^[0-9A-F]{40}$ ]]; then
    echo "::error::The Academia beta certificate was imported but its code-signing identity is unavailable."
    exit 1
fi

echo "identity=$IDENTITY" >> "$GITHUB_OUTPUT"
echo "keychain-path=$KEYCHAIN_PATH" >> "$GITHUB_OUTPUT"
echo "Imported Academia's stable self-signed beta code-signing identity."
