import WebKit
import XCTest
@testable import Hologram

@MainActor
final class WebShellScrollLockTests: XCTestCase {
    func testScrollViewIsVerticalOnlyAndUnzoomable() {
        let scroll = UIScrollView()
        scroll.alwaysBounceHorizontal = true
        scroll.contentInsetAdjustmentBehavior = .automatic
        let coordinator = WebShell.Coordinator()
        coordinator.pinZoom(in: scroll)
        XCTAssertFalse(scroll.alwaysBounceHorizontal)
        XCTAssertTrue(scroll.isDirectionalLockEnabled)
        XCTAssertEqual(scroll.contentInsetAdjustmentBehavior, .never)
        XCTAssertEqual(scroll.minimumZoomScale, 1)
        XCTAssertEqual(scroll.maximumZoomScale, 1)
        XCTAssertFalse(scroll.showsHorizontalScrollIndicator)
    }

    func testSidewaysOffsetIsClampedToZero() {
        let scroll = UIScrollView(frame: CGRect(x: 0, y: 0, width: 300, height: 600))
        scroll.contentSize = CGSize(width: 900, height: 2000)
        scroll.contentOffset = CGPoint(x: 120, y: 40)
        WebShell.Coordinator().scrollViewDidScroll(scroll)
        XCTAssertEqual(scroll.contentOffset.x, 0)
        XCTAssertEqual(scroll.contentOffset.y, 40, "vertical scrolling is untouched")
    }

    func testSessionDisablesBackForwardSwipeAndInjectsViewportMeta() {
        let session = WebSession(url: URL(string: "about:blank")!)
        XCTAssertFalse(session.webView.allowsBackForwardNavigationGestures)
        XCTAssertFalse(session.webView.scrollView.alwaysBounceHorizontal)
        XCTAssertTrue(WebSession.viewportScript.contains("maximum-scale=1"))
        XCTAssertTrue(WebSession.viewportScript.contains("user-scalable=no"))
    }
}
