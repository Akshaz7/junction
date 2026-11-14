import ARKit
import Combine
import RealityKit
import SwiftUI

@MainActor
final class ARSceneController: ObservableObject {
    @Published private(set) var status = "Loading model…"
    @Published private(set) var isFixture = false
    @Published private(set) var isLoaded = false
    @Published private(set) var isPlaced = false
    @Published private(set) var scale: Float = 0.01

    private(set) var sceneIndex: SceneIndex?
    private weak var arView: ARView?
    private var model: ModelEntity?
    private var anchor: AnchorEntity?
    private var updateSubscription: (any Cancellable)?
    private var gestureRecognizers: [UIGestureRecognizer] = []

    var scaleLabel: String { "1:\(Int((1 / scale).rounded()))" }
    var isSupported: Bool { ARWorldTrackingConfiguration.isSupported }

    func attach(to view: ARView) {
        arView = view
        guard isSupported else {
            status = "Augmented reality requires a supported iPhone or iPad."
            return
        }
        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal]
        view.session.run(configuration)
        updateSubscription = view.scene.subscribe(to: SceneEvents.Update.self) { [weak self] _ in
            self?.syncGestureScale()
        }
    }

    func load(url: URL?) async {
        guard isSupported else { return }
        do {
            let loaded = try await ARSceneLoader.load(url: url)
            try Task.checkCancellation()
            let content = loaded.entity
            sceneIndex = SceneIndex(root: content)
            let bounds = content.visualBounds(relativeTo: nil)
            // Keep the loaded prim hierarchy intact, with its bottom on the surface.
            content.position.y -= bounds.min.y
            let container = ModelEntity()
            container.name = "placement-container"
            container.addChild(content)
            let localBounds = container.visualBounds(relativeTo: container)
            let size = simd_max(localBounds.extents, SIMD3<Float>(repeating: 0.001))
            let shape = ShapeResource.generateBox(size: size).offsetBy(translation: localBounds.center)
            container.components.set(CollisionComponent(shapes: [shape]))
            container.scale = SIMD3(repeating: scale)
            model = container
            isFixture = loaded.isFixture
            isLoaded = true
            status = "Move your device to find a flat surface, then tap to place."
        } catch is CancellationError {
            return
        } catch {
            status = "Unable to load model. \(error.localizedDescription)"
        }
    }

    func place(at point: CGPoint) {
        guard !isPlaced, let view = arView, let model,
              let hit = view.raycast(from: point, allowing: .existingPlaneGeometry,
                                     alignment: .horizontal).first else { return }
        let anchor = AnchorEntity(world: hit.worldTransform)
        anchor.addChild(model)
        view.scene.addAnchor(anchor)
        self.anchor = anchor
        gestureRecognizers = view.installGestures([.translation, .rotation, .scale], for: model)
            .map { $0 as UIGestureRecognizer }
        isPlaced = true
        status = "Pinch to scale, rotate with two fingers, or drag to move."
    }

    func setScale(_ value: Float) {
        let clamped = min(max(value, 0.01), 1)
        model?.scale = SIMD3(repeating: clamped)
        if abs(scale - clamped) > 0.00001 { scale = clamped }
    }

    private func syncGestureScale() {
        guard isPlaced, let model else { return }
        setScale(model.scale.x)
    }

    func reset() {
        removeGestures()
        model?.removeFromParent()
        if let anchor { arView?.scene.removeAnchor(anchor) }
        anchor = nil
        model?.transform = Transform(scale: SIMD3(repeating: 0.01))
        scale = 0.01
        isPlaced = false
        status = "Tap a detected flat surface to place the model again."
    }

    func detach() {
        updateSubscription?.cancel()
        updateSubscription = nil
        removeGestures()
        arView?.session.pause()
        arView?.scene.anchors.removeAll()
        arView = nil
    }

    private func removeGestures() {
        for gesture in gestureRecognizers { arView?.removeGestureRecognizer(gesture) }
        gestureRecognizers.removeAll()
    }
}

struct ARSceneView: UIViewRepresentable {
    let controller: ARSceneController

    func makeCoordinator() -> Coordinator { Coordinator(controller: controller) }

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        if controller.isSupported {
            let coaching = ARCoachingOverlayView()
            coaching.session = view.session
            coaching.goal = .horizontalPlane
            coaching.activatesAutomatically = true
            coaching.translatesAutoresizingMaskIntoConstraints = false
            view.addSubview(coaching)
            NSLayoutConstraint.activate([
                coaching.leadingAnchor.constraint(equalTo: view.leadingAnchor),
                coaching.trailingAnchor.constraint(equalTo: view.trailingAnchor),
                coaching.topAnchor.constraint(equalTo: view.topAnchor),
                coaching.bottomAnchor.constraint(equalTo: view.bottomAnchor)
            ])
            let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tap(_:)))
            view.addGestureRecognizer(tap)
        }
        controller.attach(to: view)
        return view
    }

    func updateUIView(_ view: ARView, context: Context) {}

    static func dismantleUIView(_ view: ARView, coordinator: Coordinator) {
        coordinator.controller.detach()
    }

    @MainActor
    final class Coordinator: NSObject {
        let controller: ARSceneController
        init(controller: ARSceneController) { self.controller = controller }

        @objc func tap(_ gesture: UITapGestureRecognizer) {
            controller.place(at: gesture.location(in: gesture.view))
        }
    }
}
