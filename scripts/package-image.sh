#!/usr/bin/env bash
set -euo pipefail

output=${1:?Output directory required}
revision=$(git rev-parse HEAD)
version=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
[[ "$(uname -m)" == "$ARCH" && "$revision" == "$GITHUB_SHA" ]]
image="localhost/synthetic-sequencer:git-$revision-$ARCH"
archive="synthetic-sequencer-linux-$ARCH.tar.gz"
mkdir -p "$output"

docker build --provenance=false --platform "$PLATFORM" \
  --label "org.opencontainers.image.source=$GITHUB_SERVER_URL/$GITHUB_REPOSITORY" \
  --label "org.opencontainers.image.revision=$revision" \
  --label "org.opencontainers.image.version=$version" --tag "$image" .
[[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")" == "$PLATFORM" ]]
docker run --rm --network none "$image" --help
docker image save "$image" | gzip -n > "$output/$archive"
cd "$output"
config=$(tar -xOzf "$archive" manifest.json | jq -er 'if length == 1 then .[0].Config else error("expected one image") end')
image_id="sha256:$(tar -xOzf "$archive" "$config" | sha256sum | cut -d' ' -f1)"
manifest_digest=$(tar -xOzf "$archive" index.json | jq -er 'if (.manifests | length) == 1 then .manifests[0].digest else error("expected one image manifest") end')
sha256sum "$archive" > "$archive.sha256"
digest=$(cut -d' ' -f1 "$archive.sha256")
jq -n --arg version "$version" --arg platform "$PLATFORM" --arg image "$image" \
  --arg id "$image_id" --arg manifest "$manifest_digest" --arg revision "$revision" --arg archive "$archive" \
  --arg digest "$digest" --arg repo "$GITHUB_REPOSITORY" --arg run "$GITHUB_RUN_ID" \
  '{schema_version: 1, kind: "synthetic-sequencer", version: $version, platform: $platform,
    image: $image, image_id: $id, image_manifest_digest: $manifest, source_revision: $revision, archive: $archive,
    archive_sha256: $digest, publication: {repository: $repo,
    workflow: ".github/workflows/producer-image.yml", run_id: $run}}' > "$archive.manifest.json"
