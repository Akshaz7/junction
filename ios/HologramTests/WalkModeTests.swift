import XCTest
@testable import Hologram

final class WalkModeTests: XCTestCase {
    @MainActor
    func testWalkModeLocksScaleAndRestoresPreviousTableScale() {
        let controller = ARSceneController()
        controller.setScale(0.2)
        controller.setWalking(true)
        XCTAssertTrue(controller.isWalking)
        XCTAssertEqual(controller.scale, 1)
        controller.setScale(0.03)
        XCTAssertEqual(controller.scale, 1, "Walking must stay at life size")
        controller.reset()
        XCTAssertTrue(controller.isWalking)
        XCTAssertEqual(controller.scale, 1, "Reset must not return walking to table scale")
        controller.setWalking(false)
        XCTAssertFalse(controller.isWalking)
        XCTAssertEqual(controller.scale, 0.2, accuracy: 0.00001)
        XCTAssertNil(controller.cameraInModel)
        XCTAssertNil(controller.guide)
    }
}
