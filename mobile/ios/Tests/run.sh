#!/bin/bash
set -euo pipefail
mobile_tests_dir="$(cd "$(dirname "$0")" && pwd)"
mobile_test_build="$(mktemp -d "${TMPDIR:-/tmp}/stimma-mobile-tests.XXXXXX")"
trap 'rm -rf "$mobile_test_build"' EXIT
node --test --experimental-strip-types "$mobile_tests_dir/local_storage.test.mjs" "$mobile_tests_dir/../../../frontend/tests/websocketResume.test.mjs" "$mobile_tests_dir/../../../frontend/tests/connectionPresentation.test.mjs" "$mobile_tests_dir/../../../frontend/tests/viewportRotation.test.mjs"
xcrun swiftc -swift-version 5 "$mobile_tests_dir/../Sources/LocalStoragePersistence.swift" "$mobile_tests_dir/LocalStorageChecks.swift" -o "$mobile_test_build/local-storage-checks"
"$mobile_test_build/local-storage-checks"
xcrun swiftc -swift-version 5 "$mobile_tests_dir/../Sources/MobileTransport.swift" "$mobile_tests_dir/TransportChecks.swift" -o "$mobile_test_build/transport-checks"
python3 "$mobile_tests_dir/fixture.py" "$mobile_test_build/transport-checks"
xcrun swiftc -swift-version 5 "$mobile_tests_dir/../Sources/AuthCallbackListener.swift" "$mobile_tests_dir/AuthCallbackChecks.swift" -o "$mobile_test_build/auth-callback-checks"
"$mobile_test_build/auth-callback-checks"
xcrun swiftc -swift-version 5 "$mobile_tests_dir/../Sources/UIPackageCache.swift" "$mobile_tests_dir/UIPackageChecks.swift" -o "$mobile_test_build/ui-package-checks"
python3 "$mobile_tests_dir/ui_package_fixture.py" "$mobile_test_build/ui-package-checks"
