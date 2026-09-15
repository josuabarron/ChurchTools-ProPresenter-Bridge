#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPO_DIR=$(CDPATH= cd -- "$PROJECT_DIR/.." && pwd)
APP_NAME="ChurchTools Bridge"
APP_DIR="$PROJECT_DIR/.build/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
DIST_DIR="$PROJECT_DIR/.build/dist"
ZIP_PATH="$DIST_DIR/$APP_NAME.zip"
SIGN_IDENTITY=${CODE_SIGN_IDENTITY:--}

# Version aus der einen Quelle im Repo-Wurzelverzeichnis. Wird hier in den
# fertigen Bundle kopiert – Resources/Info.plist bleibt dadurch unverändert
# und muss nicht bei jedem Release von Hand nachgezogen werden.
if [ ! -f "$REPO_DIR/VERSION" ]; then
    echo "VERSION fehlt: $REPO_DIR/VERSION" >&2
    exit 1
fi
APP_VERSION=$(tr -d '[:space:]' < "$REPO_DIR/VERSION")
[ -n "$APP_VERSION" ] || { echo "VERSION ist leer" >&2; exit 1; }
# CFBundleVersion muss numerisch sein; aus der Version abgeleitet.
BUILD_NUMBER=$(printf '%s' "$APP_VERSION" | awk -F. '{ printf "%d%d%d", $1, $2, $3 }')

cd "$PROJECT_DIR"
swift build -c release

rm -rf "$APP_DIR"
mkdir -p "$CONTENTS_DIR/MacOS" "$CONTENTS_DIR/Resources" "$DIST_DIR"
cp "$PROJECT_DIR/.build/release/ChurchToolsProPresenterBridge" "$CONTENTS_DIR/MacOS/"
cp "$PROJECT_DIR/Resources/Info.plist" "$CONTENTS_DIR/Info.plist"
cp "$PROJECT_DIR/LICENSE.md" "$CONTENTS_DIR/Resources/LICENSE.md"

# Version und Build-Nummer in den kopierten Plist schreiben.
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$CONTENTS_DIR/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_NUMBER" "$CONTENTS_DIR/Info.plist"

xcrun actool "$PROJECT_DIR/Resources/Assets.xcassets" \
    --compile "$CONTENTS_DIR/Resources" \
    --platform macosx \
    --minimum-deployment-target 13.0 \
    --app-icon AppIcon \
    --output-partial-info-plist "$PROJECT_DIR/.build/asset-info.plist"

if [ "$SIGN_IDENTITY" = "-" ]; then
    codesign --force --deep --sign - "$APP_DIR"
    echo "Signed ad-hoc. Set CODE_SIGN_IDENTITY to a Developer ID Application identity for trusted distribution."
else
    codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP_DIR"
fi

codesign --verify --deep --strict --verbose=2 "$APP_DIR"

# Version im Log, damit ein falscher Wert im CI sofort auffällt.
echo "Version $APP_VERSION (Build $BUILD_NUMBER)"
/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$CONTENTS_DIR/Info.plist"

rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$ZIP_PATH"

if [ -n "${NOTARY_PROFILE:-}" ] && [ "$SIGN_IDENTITY" != "-" ]; then
    xcrun notarytool submit "$ZIP_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$APP_DIR"
    rm -f "$ZIP_PATH"
    ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$ZIP_PATH"
fi

echo "$APP_DIR"
echo "$ZIP_PATH"