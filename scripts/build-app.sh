#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP_NAME="ChurchTools Bridge"
APP_DIR="$PROJECT_DIR/.build/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
DIST_DIR="$PROJECT_DIR/.build/dist"
ZIP_PATH="$DIST_DIR/$APP_NAME.zip"
SIGN_IDENTITY=${CODE_SIGN_IDENTITY:--}

cd "$PROJECT_DIR"
swift build -c release

rm -rf "$APP_DIR"
mkdir -p "$CONTENTS_DIR/MacOS" "$CONTENTS_DIR/Resources" "$DIST_DIR"
cp "$PROJECT_DIR/.build/release/ChurchToolsProPresenterBridge" "$CONTENTS_DIR/MacOS/"
cp "$PROJECT_DIR/Resources/Info.plist" "$CONTENTS_DIR/Info.plist"

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
