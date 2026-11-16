import Photos
import UIKit
import WebKit

/// Resumes a continuation once, however many system callbacks report the same ending.
final class ResumeOnce<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<T, Never>?
    init(_ continuation: CheckedContinuation<T, Never>) { self.continuation = continuation }
    func resume(_ value: T) {
        lock.lock(); let pending = continuation; continuation = nil; lock.unlock()
        pending?.resume(returning: value)
    }
}

@MainActor
enum PhoneExports {
    /// The view controller a sheet can be presented from right now.
    static func presenter(for view: UIView?) throws -> UIViewController {
        guard var presenter = view?.window?.rootViewController else { throw ExportError("Cannot open this sheet right now.") }
        while let presented = presenter.presentedViewController { presenter = presented }
        guard !presenter.isBeingDismissed else { throw ExportError("Please close the current sheet and try again.") }
        return presenter
    }

    /// Opens the system print dialog for the page's print layout and returns when the dialog closes.
    static func print(_ webView: WKWebView, title: String) async {
        let info = UIPrintInfo.printInfo()
        info.jobName = title
        info.outputType = .general
        let printer = UIPrintInteractionController.shared
        printer.printInfo = info
        printer.printFormatter = webView.viewPrintFormatter()
        // The WebView's own dark background would show around the printed content; paper is white.
        let background = webView.backgroundColor
        let underPage = webView.underPageBackgroundColor
        webView.backgroundColor = .white
        webView.scrollView.backgroundColor = .white
        webView.underPageBackgroundColor = .white
        defer {
            webView.backgroundColor = background
            webView.scrollView.backgroundColor = background
            webView.underPageBackgroundColor = underPage
        }
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            let once = ResumeOnce(continuation)
            if !printer.present(animated: true, completionHandler: { _, _, _ in once.resume(()) }) { once.resume(()) }
        }
    }

    /// Adds a picture or video to Photos. False when Photos access is refused or Photos can't take the file.
    static func saveToPhotos(_ file: URL, video: Bool) async -> Bool {
        var status = PHPhotoLibrary.authorizationStatus(for: .addOnly)
        if status == .notDetermined { status = await PHPhotoLibrary.requestAuthorization(for: .addOnly) }
        guard status == .authorized || status == .limited else { return false }
        let name = file.lastPathComponent
        do {
            try await PHPhotoLibrary.shared().performChanges {
                let options = PHAssetResourceCreationOptions()
                options.originalFilename = name
                PHAssetCreationRequest.forAsset().addResource(with: video ? .video : .photo, fileURL: file, options: options)
            }
            return true
        } catch {
            return false
        }
    }
}

/// The system Files export picker for one file. Resolves true once the person picks a place, false on cancel.
@MainActor
final class FilesExport: NSObject, UIDocumentPickerDelegate {
    private var once: ResumeOnce<Bool>?

    func run(_ file: URL, from presenter: UIViewController, sourceView: UIView?) async -> Bool {
        let picker = UIDocumentPickerViewController(forExporting: [file], asCopy: true)
        picker.delegate = self
        picker.popoverPresentationController?.sourceView = sourceView
        return await withCheckedContinuation { continuation in
            once = ResumeOnce(continuation)
            presenter.present(picker, animated: true)
        }
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) { finish(true) }
    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) { finish(false) }

    func finish(_ saved: Bool) { once?.resume(saved); once = nil }
}
