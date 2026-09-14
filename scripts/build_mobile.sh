#!/usr/bin/env bash
# Sprint 10 — build both mobile apps for release.
#
# Prereqs:
#  - Android: android/key.properties present with signing config (see mobile/README.md)
#  - iOS: Apple Developer team signed into Xcode; provisioning profiles valid
#  - Firebase config files (google-services.json, GoogleService-Info.plist) in place
#
# Env:
#   API_BASE — the backend base URL (default: https://manasety-school.sd/api)

set -euo pipefail
API_BASE="${API_BASE:-https://manasety-school.sd/api}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FLUTTER="${FLUTTER:-flutter}"

echo "==> Building against API_BASE=$API_BASE"

for app in teacher_app parent_app; do
  echo ""
  echo "==> $app — Android App Bundle"
  (cd "$ROOT/mobile/$app" && "$FLUTTER" build appbundle --release \
     --dart-define=API_BASE="$API_BASE")
  aab="$ROOT/mobile/$app/build/app/outputs/bundle/release/app-release.aab"
  if [ -f "$aab" ]; then
    echo "   → $aab"
  else
    echo "   ⚠️  .aab not produced (signing config missing?)"
  fi
done

# iOS builds only work on macOS with Xcode installed
if [[ "$OSTYPE" == "darwin"* ]]; then
  for app in teacher_app parent_app; do
    echo ""
    echo "==> $app — iOS IPA"
    (cd "$ROOT/mobile/$app" && "$FLUTTER" build ipa --release \
       --dart-define=API_BASE="$API_BASE") || {
      echo "   ⚠️  IPA build failed (needs Apple Developer signing)"
    }
  done
else
  echo ""
  echo "==> Skipping iOS builds (not macOS)"
fi

echo ""
echo "✅ Done. Next: upload .aab to Play Console + .ipa via Xcode Organizer."
