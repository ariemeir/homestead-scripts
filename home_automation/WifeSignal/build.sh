#!/bin/bash
set -euo pipefail

PROJECT_DIR="$HOME/dev/scripts/home_automation/WifeSignalDevice"
API_KEY=/Users/ariemeir/keys/AuthKey_6V6972M9FV.p8
KEY_ID=6V6972M9FV
ISSUER_ID=870ebf89-57cc-4ef0-b499-bcb9aed264d4
ARCHIVE=/tmp/WifeSignal.xcarchive
EXPORT_DIR=/tmp/WifeSignal-export

cd "$PROJECT_DIR"

CURRENT=$(grep 'CURRENT_PROJECT_VERSION:' app/project.yml | head -1 | grep -oE '[0-9]+')
   NEXT=$((CURRENT + 1))
   sed -i '' "s/CURRENT_PROJECT_VERSION: \"$CURRENT\"/CURRENT_PROJECT_VERSION: \"$NEXT\"/" app/project.yml

# Keychain must be unlocked and codesign-authorized (survives across SSH sessions
# once run, but re-run after reboot).
security unlock-keychain ~/Library/Keychains/login.keychain-db
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s ~/Library/Keychains/login.keychain-db > /dev/null

xcodegen generate --spec app/project.yml

rm -rf "$ARCHIVE" "$EXPORT_DIR"

xcodebuild -project app/WifeSignal.xcodeproj -scheme WifeSignal \
  -destination 'generic/platform=iOS' \
  archive -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$API_KEY" \
  -authenticationKeyID "$KEY_ID" \
  -authenticationKeyIssuerID "$ISSUER_ID"

xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist "$PROJECT_DIR/ExportOptions.plist" \
  -exportPath "$EXPORT_DIR" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$API_KEY" \
  -authenticationKeyID "$KEY_ID" \
  -authenticationKeyIssuerID "$ISSUER_ID"

curl -s https://api.pushover.net/1/messages.json \
     -F "token=YOUR_APP_TOKEN" \
     -F "user=YOUR_USER_KEY" \
     -F "message=WifeSignal build $NEXT uploaded to TestFlight" > /dev/null

echo "✅ Uploaded. Check TestFlight in ~10 min."
