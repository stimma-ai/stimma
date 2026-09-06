import XCTest

final class ShellUITests: XCTestCase {
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
