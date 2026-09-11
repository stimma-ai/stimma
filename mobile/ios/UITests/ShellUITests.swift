import XCTest
import Network

final class ShellUITests: XCTestCase {
    func testManualDevServerLoadsNativeBridgeAndDisconnects() throws {
        // A disposable HTTP frontend proves WKWebView loads a live origin and
        // accepts bridge calls there, without a cloud account or UI package.
        let listener = try NWListener(using: .tcp, on: .any)
        let ready = expectation(description: "Dev frontend listening")
        listener.stateUpdateHandler = { if case .ready = $0 { ready.fulfill() } }
        listener.newConnectionHandler = { connection in
            connection.start(queue: .global())
            connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { _, _, _, _ in
                let html = """
                <!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
                <body><h1>Live dev frontend</h1><p id="result">Waiting for native bridge</p>
                <button onclick="native('disconnect')">Disconnect</button>
                <script>
                const native = (method) => window.webkit.messageHandlers.stimma.postMessage({method});
                native('getState').then(state => {
                  document.getElementById('result').textContent = state.activeDeviceId.startsWith('dev:') ? 'Dev bridge ready' : 'Wrong server';
                  return native('interfaceReady');
                });
                </script>
                """
                let bytes = Data(html.utf8)
                var response = Data("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: \(bytes.count)\r\nConnection: close\r\n\r\n".utf8)
                response.append(bytes)
                connection.send(content: response, completion: .contentProcessed { _ in connection.cancel() })
            }
        }
        listener.start(queue: .global())
        defer { listener.cancel() }
        wait(for: [ready], timeout: 5)
        let port = try XCTUnwrap(listener.port).rawValue
        let app = XCUIApplication()
        app.launchArguments = ["-mobile.devServerAddress", ""]
        app.launch()
        let dev = app.webViews.buttons["Dev server"]
        XCTAssertTrue(dev.waitForExistence(timeout: 15), app.debugDescription)
        dev.tap()
        let address = app.webViews.textFields["Server IP and frontend port"]
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        address.tap()
        address.typeText("127.0.0.1:\(port)")
        app.webViews.buttons["Connect to dev server"].tap()
        XCTAssertTrue(app.webViews.staticTexts["Dev bridge ready"].waitForExistence(timeout: 15), app.debugDescription)
        XCTAssertFalse(app.buttons["Dev"].exists)
        app.webViews.buttons["Disconnect"].tap()
        XCTAssertTrue(app.webViews.buttons["Dev server"].waitForExistence(timeout: 10), app.debugDescription)
    }

    func testAuthEndpointConnectivity() {
        let app = XCUIApplication()
        app.launchArguments = ["--auth-network-check"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Auth network check passed"].waitForExistence(timeout: 90), app.debugDescription)
    }

    func testKeychainPersistsAcrossLaunches() {
        let app = XCUIApplication()
        for stage in ["write", "verify"] {
            app.launchArguments = ["--keychain-check", stage]
            app.launch()
            XCTAssertTrue(app.staticTexts["Keychain check passed"].waitForExistence(timeout: 10), app.debugDescription)
            app.terminate()
        }
    }

    func testBrowserSignInOpensAuthenticationSession() {
        let app = XCUIApplication()
        app.launch()
        let signIn = app.webViews.buttons["Sign in"]
        XCTAssertTrue(signIn.waitForExistence(timeout: 10))
        let welcome = XCTAttachment(screenshot: app.screenshot())
        welcome.name = "Stimma welcome"
        welcome.lifetime = .keepAlways
        add(welcome)
        signIn.tap()
        let consent = app.alerts.buttons["Continue"]
        if consent.waitForExistence(timeout: 3) { consent.tap() }
        else {
            let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
            let button = springboard.buttons["Continue"]
            if button.waitForExistence(timeout: 3) { button.tap() }
        }
        XCTAssertTrue(app.webViews.textFields["Email"].waitForExistence(timeout: 30), app.debugDescription)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "System browser sign in"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    func testLibraryLoadsAfterBackgroundResume() {
        let app = XCUIApplication()
        app.launchArguments = ["--local-backend-port", "9480"]
        app.launch()
        let browse = app.webViews.links["View all"]
        XCTAssertTrue(browse.waitForExistence(timeout: 30), app.debugDescription)
        XCUIDevice.shared.press(.home)
        app.activate()
        XCTAssertTrue(browse.waitForExistence(timeout: 15), app.debugDescription)
        browse.tap()
        let assets = app.webViews.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'assets'")).firstMatch
        XCTAssertTrue(assets.waitForExistence(timeout: 30), app.debugDescription)
        // A second resume must preserve the open browser rather than reload Home.
        XCUIDevice.shared.press(.home)
        app.activate()
        XCTAssertTrue(assets.waitForExistence(timeout: 15), app.debugDescription)
        app.webViews.buttons["Menu"].tap()
        XCTAssertTrue(app.webViews.buttons["Stimma account"].waitForExistence(timeout: 5))
    }

    func testRealLibraryLoadsInWebView() {
        let app = XCUIApplication()
        app.launchArguments = ["--local-backend-port", "9480"]
        app.launch()
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 30))
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "iOS compact library"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        XCTAssertFalse(app.buttons["Get started"].exists, "Phone should not enter desktop onboarding")
        let browse = app.webViews.links["View all"]
        XCTAssertTrue(browse.waitForExistence(timeout: 30), app.debugDescription)
        browse.tap()
        XCTAssertTrue(app.webViews.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'assets'")).firstMatch.waitForExistence(timeout: 30), app.debugDescription)
        app.webViews.buttons["Menu"].tap()
        let account = app.webViews.buttons["Stimma account"]
        XCTAssertTrue(account.waitForExistence(timeout: 5))
        account.tap()
        XCTAssertTrue(app.webViews.buttons["Sign out"].waitForExistence(timeout: 5))
        app.webViews.buttons["Disconnect from server"].tap()
        XCTAssertTrue(app.webViews.buttons["Sign in"].waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertFalse(app.webViews.links["View all"].exists)
    }
}
