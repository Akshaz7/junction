import ARKit
import Combine
import RealityKit
import SwiftUI

@MainActor
final class ARSceneController: ObservableObject {
    @Published private(set) var status = "Loading model…"
    @Published private(set) var isFixture = false
    @Published private(set) var isBundledDemo = false
    @Published private(set) var attribution: SceneAttribution?
    @Published var demoDocID: String? = nil
    @Published private(set) var isLoaded = false
    @Published private(set) var isPlaced = false
    @Published private(set) var scale: Float = 0.01
    @Published private(set) var isWalking = false
    @Published private(set) var manifest: SceneManifest?
    @Published private(set) var highlightedItemIDs: [String] = []
    @Published private(set) var cameraInModel: simd_float4x4?
    @Published private(set) var guide: WalkGuide?
    @Published private(set) var targetItemID: String?
    @Published private(set) var selectedItem: ItemCardModel?
    @Published private(set) var activeStorey: String?
    @Published private(set) var showRoof = false
    private(set) var activeDocID: String?
    private var requestedDocID: String?
    private var pendingLiveCommands: [LiveSocket.Command] = []
    private(set) var hiddenItemIDs: Set<String> = []
    private var appliedEditIDs: Set<String> = []
    private var visibilityTasks: [String: Task<Void, Never>] = [:]
    private var visibilityTargets: [String: Bool] = [:]
    private var originalOpacity: [String: Float] = [:]

    private(set) var sceneIndex: SceneIndex?
    private(set) var highlightController: HighlightController?
    private weak var arView: ARView?
    private var model: ModelEntity?
    private var content: Entity?
    private var originalContentTransform = Transform()
    private var tableFloor: Float = 0
    private var tableScale: Float = 0.01
    private var lastGuideUpdate: TimeInterval = 0
    private var anchor: AnchorEntity?
    private var updateSubscription: (any Cancellable)?
    private var gestureRecognizers: [UIGestureRecognizer] = []
    private var itemPicker: ItemPicker?
    private let selectionOutline = ItemSelectionOutline()
    private var originalVisibility: [String: Bool] = [:]

    var scaleLabel: String { "1:\(Int((1 / scale).rounded()))" }
    var isSupported: Bool { ARWorldTrackingConfiguration.isSupported }
    var cutawayStoreys: [SceneManifest.Storey] { manifest.map { CutawayPolicy(manifest: $0).storeys } ?? [] }
    var canStepStoreyDown: Bool { storeyIndex.map { $0 > 0 } ?? false }
    var canStepStoreyUp: Bool { storeyIndex.map { $0 + 1 < cutawayStoreys.count } ?? false }
    private var storeyIndex: Int? { cutawayStoreys.firstIndex { $0.name == activeStorey } }

    /// Logical visibility updates immediately; the rendered entity may still be fading out.
    var visibleItemIDs: Set<String> {
        guard let manifest else { return [] }
        let cutaway = CutawayPolicy(manifest: manifest).hiddenUSDNames(activeStorey: activeStorey,
                                                                      showRoof: showRoof)
        return Set(manifest.items.compactMap { id, item in
            !hiddenItemIDs.contains(id) && !cutaway.contains(item.usd_name)
                && (originalVisibility[item.usd_name] ?? true)
                && sceneIndex?.entitiesByUSDName[item.usd_name] != nil ? id : nil
        })
    }

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
            self?.updateWalkGuide()
        }
    }

    func load(docID: String? = nil, url: URL?, manifestURL: URL? = nil, itemIDs: [String] = [],
              cameraTargetItemID: String? = nil) async {
        resetPlacement()
        cancelVisibilityTransitions()
        highlightController?.clear()
        isLoaded = false
        isFixture = false
        isBundledDemo = false
        attribution = nil
        manifest = nil
        activeDocID = nil
        isWalking = false
        scale = 0.01
        tableScale = 0.01
        status = "Loading model…"
        requestedDocID = docID
        pendingLiveCommands = []
        hiddenItemIDs = []
        appliedEditIDs = []
        visibilityTargets = [:]
        originalOpacity = [:]
        do {
            let loaded = try await ARSceneLoader.load(docID: docID, url: url, manifestURL: manifestURL)
            try Task.checkCancellation()
            let content = loaded.entity
            self.content = content
            originalContentTransform = content.transform
            manifest = loaded.manifest
            attribution = loaded.attribution
            isBundledDemo = loaded.isBundledDemo
            activeDocID = loaded.manifest?.doc_id ?? (loaded.isFixture ? "fixture__ios" : docID)
            sceneIndex = SceneIndex(root: content)
            originalVisibility = sceneIndex?.entitiesByUSDName.mapValues(\.isEnabled) ?? [:]
            originalOpacity = sceneIndex?.entitiesByUSDName.mapValues {
                $0.components[OpacityComponent.self]?.opacity ?? 1
            } ?? [:]
            showRoof = false
            highlightController = HighlightController(root: content)
            itemPicker = loaded.manifest.map { ItemPicker(manifest: $0) }
            // Generate mesh hit targets before answer labels or selection outlines exist.
            content.generateCollisionShapes(recursive: true)
            let bounds = content.visualBounds(relativeTo: nil)
            tableFloor = bounds.min.y
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
            // Never put evidence for an unavailable document on unrelated fixture items.
            setHighlights(docID == nil || docID == activeDocID ? itemIDs : [],
                          cameraTargetItemID: docID == nil || docID == activeDocID ? cameraTargetItemID : nil)
            let pending = pendingLiveCommands
            pendingLiveCommands = []
            for command in pending { applyLiveCommand(command) }
            status = isSupported ? "Move your device to find a flat surface, then tap to place."
                : "Augmented reality requires a supported iPhone or iPad."
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
        if isWalking {
            guard let plane = hit.anchor as? ARPlaneAnchor, plane.classification == .floor else {
                status = "Move your device to detect the floor, then tap the floor to start walking."
                return
            }
        }
        // Keep scene Y vertical even if the estimated plane is slightly tilted.
        let anchor = AnchorEntity(world: hit.worldTransform.columns.3.xyz)
        anchor.addChild(model)
        view.scene.addAnchor(anchor)
        self.anchor = anchor
        if !isWalking { installTableGestures(on: view, model: model) }
        isPlaced = true
        status = isWalking ? "Walk at 1:1. Select an item on the map to guide you."
            : "Tap an item for details. Pinch to scale, rotate with two fingers, or drag to move."
    }

    func tap(at point: CGPoint) {
        guard isPlaced else {
            place(at: point)
            return
        }
        guard let view = arView, let itemPicker else {
            dismissSelectedItem()
            return
        }
        // The placement container also has a collision box for gestures. Skip it
        // and resolve the nearest real mesh hit through its USD prim parents.
        let itemID = view.hitTest(point, query: .all).sorted { $0.distance < $1.distance }
            .lazy.filter { $0.entity.isActive }.compactMap { itemPicker.itemID(for: $0.entity) }.first
        guard let itemID, let item = manifest?.items[itemID],
              let entity = sceneIndex?.entitiesByUSDName[item.usd_name] else {
            dismissSelectedItem()
            return
        }
        selectedItem = ItemCardModel(itemID: itemID, item: item)
        selectionOutline.select(entity)
    }

    func dismissSelectedItem() {
        selectedItem = nil
        selectionOutline.clear()
    }

    func setScale(_ value: Float) {
        let clamped: Float = isWalking ? 1 : min(max(value, 0.01), 1)
        model?.scale = SIMD3(repeating: clamped)
        if abs(scale - clamped) > 0.00001 { scale = clamped }
    }

    private func syncGestureScale() {
        guard isPlaced, let model else { return }
        setScale(model.scale.x)
    }

    func setWalking(_ walking: Bool) {
        guard walking != isWalking else { return }
        if walking { tableScale = scale }
        isWalking = walking
        // A table hit is not a floor hit. Require fresh floor placement on entry.
        resetPlacement()
        setScale(walking ? 1 : tableScale)
        content?.transform = originalContentTransform
        content?.position.y -= walking ? (manifest?.floorElevation ?? 0) : tableFloor
        status = walking ? "Move your device to detect the floor, then tap the floor to start walking."
            : "Tap a detected flat surface to place the model."
    }

    func setHighlights(_ itemIDs: [String], cameraTargetItemID: String? = nil,
                       labels: [String: String] = [:]) {
        highlightedItemIDs = itemIDs
        // Measure label positions against the full model before hiding the new cutaway.
        let visibility = sceneIndex?.entitiesByUSDName.mapValues(\.isEnabled) ?? [:]
        for item in manifest?.items.values ?? Dictionary<String, SceneManifest.Item>().values {
            sceneIndex?.entitiesByUSDName[item.usd_name]?.isEnabled = originalVisibility[item.usd_name] ?? true
        }
        var resolvedLabels = manifest?.items.compactMapValues(\.tag) ?? [:]
        resolvedLabels.merge(labels) { _, explicit in explicit }
        highlightController?.highlight(itemIDs: itemIDs, labels: resolvedLabels)
        for (name, enabled) in visibility { sceneIndex?.entitiesByUSDName[name]?.isEnabled = enabled }
        targetItemID = ([cameraTargetItemID].compactMap { $0 } + itemIDs)
            .first { manifest?.items[$0]?.bbox_m != nil }
        activeStorey = manifest.map {
            CutawayPolicy(manifest: $0).activeStorey(cameraTargetItemID: cameraTargetItemID,
                                                   highlightedItemIDs: itemIDs)
        } ?? nil
        applyCutaway()
        guide = nil
        lastGuideUpdate = 0
        updateWalkGuide()
    }

    func setShowRoof(_ show: Bool) {
        showRoof = show
        applyCutaway()
    }

    func stepStorey(_ direction: Int) {
        guard let index = storeyIndex else { return }
        let next = index + direction
        guard cutawayStoreys.indices.contains(next) else { return }
        activeStorey = cutawayStoreys[next].name
        applyCutaway()
    }

    private func applyCutaway(animated: Bool = false) {
        guard let manifest else { return }
        let hidden = CutawayPolicy(manifest: manifest).hiddenUSDNames(activeStorey: activeStorey,
                                                                     showRoof: showRoof)
        let visible = visibleItemIDs
        for (id, item) in manifest.items {
            guard let entity = sceneIndex?.entitiesByUSDName[item.usd_name] else { continue }
            let enabled = visible.contains(id)
            // Cutaway wins immediately, even if an edit fade was in flight.
            let cutAway = hidden.contains(item.usd_name)
            guard visibilityTargets[id] != enabled || (cutAway && entity.isEnabled) else { continue }
            visibilityTargets[id] = enabled
            visibilityTasks[id]?.cancel()
            visibilityTasks[id] = nil
            let opacity = originalOpacity[item.usd_name] ?? 1
            if animated && !cutAway && (originalVisibility[item.usd_name] ?? true) {
                fade(entity, itemID: id, enabled: enabled, opacity: opacity)
            } else {
                entity.isEnabled = enabled
                entity.components.set(OpacityComponent(opacity: opacity))
            }
        }
        // Answer labels are siblings of item prims, so hide them explicitly as well.
        for (id, label) in highlightController?.labelsByItemID ?? [:] {
            label.isEnabled = visible.contains(id)
        }
        if let selectedItem, !visible.contains(selectedItem.id) {
            dismissSelectedItem()
        }
    }

    private func fade(_ entity: Entity, itemID: String, enabled: Bool, opacity: Float) {
        let start: Float = entity.isEnabled ? (entity.components[OpacityComponent.self]?.opacity ?? opacity) : 0
        let end: Float = enabled ? opacity : 0
        entity.components.set(OpacityComponent(opacity: start))
        entity.isEnabled = true
        visibilityTasks[itemID] = Task { [weak self, weak entity] in
            // Fifteen steps over 250 ms. Cancellation lets a later restore reverse a hide.
            for step in 1...15 {
                do { try await Task.sleep(for: .seconds(0.25 / 15)) }
                catch { return }
                guard !Task.isCancelled, let entity else { return }
                entity.components.set(OpacityComponent(opacity: start + (end - start) * Float(step) / 15))
            }
            guard let self, let entity else { return }
            entity.isEnabled = enabled
            entity.components.set(OpacityComponent(opacity: opacity))
            self.visibilityTasks[itemID] = nil
        }
    }

    private func cancelVisibilityTransitions() {
        for task in visibilityTasks.values { task.cancel() }
        visibilityTasks = [:]
    }

    private func applySceneCommand(_ command: SceneCommand) {
        let ids = Set(command.item_ids).intersection(Set(manifest?.items.keys.map { $0 } ?? []))
        switch command.op {
        case .highlight:
            setHighlights(command.item_ids, labels: command.labels ?? [:])
        case .hide:
            hiddenItemIDs.formUnion(ids)
        case .restore:
            hiddenItemIDs.subtract(ids)
        case .isolate:
            hiddenItemIDs = Set(manifest?.items.keys.map { $0 } ?? []).subtracting(ids)
        case .reset:
            hiddenItemIDs = []
            setHighlights([])
        }
        applyCutaway(animated: true)
    }

    @discardableResult
    func applyVoiceAnswer(_ answer: VoiceAnswer) -> Bool {
        guard answer.evidence.scene.doc_id == activeDocID else { return false }
        if let commands = answer.evidence.scene.commands, !commands.isEmpty {
            for command in commands { applySceneCommand(command) }
        } else {
            setHighlights(answer.evidence.scene.highlight_item_ids,
                          cameraTargetItemID: answer.evidence.scene.camera_target_item_id,
                          labels: answer.highlightLabels)
        }
        return true
    }

    func selectTarget(_ itemID: String) {
        setHighlights([itemID], cameraTargetItemID: itemID)
    }

    @discardableResult
    func applyLiveHighlight(_ request: ARRequest) -> Bool {
        applyLiveCommand(.highlight(request))
    }

    @discardableResult
    func applyLiveCommand(_ command: LiveSocket.Command) -> Bool {
        let docID: String
        switch command {
        case .highlight(let request): docID = request.docID
        case .edit(let edit): docID = edit.doc_id
        case .state(let state): docID = state.doc_id
        case .ping, .ignored: return false
        }
        if !isLoaded, docID == requestedDocID {
            pendingLiveCommands.append(command)
            return true
        }
        guard docID == activeDocID else { return false }
        switch command {
        case .highlight(let request): setHighlights(request.itemIDs)
        case .edit(let edit):
            if let id = edit.edit_id, !appliedEditIDs.insert(id).inserted { return true }
            applySceneCommand(edit.command)
        case .state(let state):
            hiddenItemIDs = Set(state.hidden).intersection(Set(manifest?.items.keys.map { $0 } ?? []))
            setHighlights(state.highlighted, labels: state.labels)
        case .ping, .ignored: break
        }
        return true
    }

    private func updateWalkGuide() {
        guard isWalking, isPlaced, let frame = arView?.session.currentFrame, let content,
              frame.timestamp - lastGuideUpdate >= 0.1 else { return }
        lastGuideUpdate = frame.timestamp
        guard case .normal = frame.camera.trackingState else {
            cameraInModel = nil
            guide = nil
            return
        }
        // Invert the entire hierarchy, including floor offset and placement translation.
        let camera = simd_inverse(content.transformMatrix(relativeTo: nil)) * frame.camera.transform
        cameraInModel = camera
        if let targetItemID, let bounds = manifest?.items[targetItemID]?.bbox_m {
            guide = WalkGuide(cameraTransform: camera, target: bounds.center)
        } else {
            guide = nil
        }
    }

    func reset() {
        resetPlacement()
        if !isWalking { tableScale = 0.01 }
        setScale(isWalking ? 1 : tableScale)
        status = isWalking ? "Tap a detected floor to place the model again."
            : "Tap a detected flat surface to place the model again."
    }

    private func resetPlacement() {
        dismissSelectedItem()
        removeGestures()
        model?.removeFromParent()
        if let anchor { arView?.scene.removeAnchor(anchor) }
        anchor = nil
        model?.transform = Transform(scale: SIMD3(repeating: scale))
        isPlaced = false
        cameraInModel = nil
        guide = nil
        lastGuideUpdate = 0
    }

    func detach() {
        cancelVisibilityTransitions()
        dismissSelectedItem()
        highlightController?.clear()
        updateSubscription?.cancel()
        updateSubscription = nil
        removeGestures()
        arView?.session.pause()
        arView?.scene.anchors.removeAll()
        arView = nil
    }

    private func installTableGestures(on view: ARView, model: ModelEntity) {
        gestureRecognizers = view.installGestures([.translation, .rotation, .scale], for: model)
            .map { $0 as UIGestureRecognizer }
    }

    private func removeGestures() {
        for gesture in gestureRecognizers { arView?.removeGestureRecognizer(gesture) }
        gestureRecognizers.removeAll()
    }
}

private extension SIMD4 where Scalar == Float {
    var xyz: SIMD3<Float> { SIMD3(x, y, z) }
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
            controller.tap(at: gesture.location(in: gesture.view))
        }
    }
}
