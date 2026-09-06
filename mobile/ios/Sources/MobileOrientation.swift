import UIKit

/// Portrait is the shell default; only an active slideshow permits landscape.
@MainActor
final class MobileAppDelegate: NSObject, UIApplicationDelegate {
    static private(set) var orientations: UIInterfaceOrientationMask = .portrait

    func application(_ application: UIApplication, supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
        Self.orientations
    }

    static func setSlideshowActive(_ active: Bool) {
        let next: UIInterfaceOrientationMask = active ? .allButUpsideDown : .portrait
        guard next != orientations else { return }
        orientations = next
        for case let scene as UIWindowScene in UIApplication.shared.connectedScenes {
            for window in scene.windows {
                var controller = window.rootViewController
                while let current = controller {
                    current.setNeedsUpdateOfSupportedInterfaceOrientations()
                    controller = current.presentedViewController
                }
            }
            // On exit, return to portrait even if the phone is still sideways.
            // On entry, UIKit follows the device and its rotation-lock setting.
            if !active {
                scene.requestGeometryUpdate(.iOS(interfaceOrientations: .portrait)) { _ in }
            }
        }
    }
}
