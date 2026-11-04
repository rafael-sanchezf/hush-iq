#!/bin/sh
# The toolbar and store icons, resized from the Hush IQ logo (512 px, the iOS app's mark). macOS `sips`, run once;
# the PNGs are committed. Usage: scripts/icons.sh path/to/hushiq-logo-512.png
set -eu
src="${1:?path to the 512 px logo}"
out="$(dirname "$0")/../icons"
mkdir -p "$out"
for n in 16 32 48 128; do
  sips -s format png -z "$n" "$n" "$src" --out "$out/icon-$n.png" >/dev/null
done
ls -l "$out"
