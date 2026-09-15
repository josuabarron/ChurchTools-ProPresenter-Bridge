#!/bin/sh
# Lokaler Bau der Mac-App auf diesem Rechner.
#
# Unterschied zu scripts/build-app.sh:
#  * actool wird nicht benutzt (dafuer waere die Xcode-Lizenz noetig).
#    Das Icon wird stattdessen mit sips/iconutil gebaut.
#  * -plugin-path zeigt auf die SwiftUI-Makros aus Xcode, weil
#    xcode-select hier auf die Command Line Tools zeigt.
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPO_DIR=$(CDPATH= cd -- "$PROJECT_DIR/.." && pwd)
APP_NAME="ChurchTools Bridge"
APP_DIR="$PROJECT_DIR/.build/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
DIST_DIR="$PROJECT_DIR/.build/dist"
ZIP_PATH="$DIST_DIR/$APP_NAME.zip"
PLUGINS="/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/usr/lib/swift/host/plugins"

VERSION=$(tr -d '[:space:]' < "$REPO_DIR/VERSION")
[ -n "$VERSION" ] || { echo "VERSION ist leer" >&2; exit 1; }
BUILD_NUMBER=$(printf '%s' "$VERSION" | awk -F. '{ printf "%d%d%d", $1, $2, $3 }')

cd "$PROJECT_DIR"
swift build -c release -Xswiftc -plugin-path -Xswiftc "$PLUGINS"

rm -rf "$APP_DIR"
mkdir -p "$CONTENTS_DIR/MacOS" "$CONTENTS_DIR/Resources" "$DIST_DIR"
cp "$PROJECT_DIR/.build/release/ChurchToolsProPresenterBridge" "$CONTENTS_DIR/MacOS/"
cp "$PROJECT_DIR/Resources/Info.plist" "$CONTENTS_DIR/Info.plist"
cp "$REPO_DIR/LICENSE.md" "$CONTENTS_DIR/Resources/LICENSE.md"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$CONTENTS_DIR/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILD_NUMBER" "$CONTENTS_DIR/Info.plist"

# --- Icon ohne actool ---
ICONSET="$PROJECT_DIR/.build/AppIcon.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
SRC="$PROJECT_DIR/Resources/Assets.xcassets/AppIcon.appiconset"
for f in "$SRC"/*.png; do
    cp "$f" "$ICONSET/$(basename "$f")"
done
iconutil -c icns "$ICONSET" -o "$CONTENTS_DIR/Resources/AppIcon.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile AppIcon" "$CONTENTS_DIR/Info.plist" 2>/dev/null || \
    /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$CONTENTS_DIR/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$CONTENTS_DIR/Info.plist" 2>/dev/null || true

codesign --force --deep --sign - "$APP_DIR"
codesign --verify --deep --strict --verbose=2 "$APP_DIR"

rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$ZIP_PATH"

echo
echo "Version $VERSION (Build $BUILD_NUMBER)"
echo "$APP_DIR"
echo "$ZIP_PATH"