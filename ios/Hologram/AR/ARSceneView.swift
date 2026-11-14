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
    @Published private(set) var sceneIdentity = SceneIdentity(requestedDocID: nil, manifest: nil)
    @Published var demoDocID: String? = nil
    @Published private(set) var isLoaded = false
    @Published private(set) var isPlaced = false
    @Published private(set) var scale: Float = 0.01
    @Published private(set) var isWalking = false
    @Published private(set) var manifest: SceneManifest?
    @Published private(set) var highlightedItemIDs: [String] = []
    /// Step scrubber state; nil when no build-up exists (nothing placed, no manifest, walk mode).
    @Published private(set) var buildState: BuildState?
    @Published private(set) var cameraInModel: simd_float4x4?
    @Published private(set) var guide: WalkGuide?
    @Published private(set) var targetItemID: String?
    @Published private(set) var selectedItem: ItemCardModel?
    @Published private(set) var activeStorey: String?
    @Published private(set) var showRoof = false
    /// True while any item is hidden by an edit; the advisor card goes away when the last one returns.
    @Published private(set) var hasHiddenItems = false
    /// Screen point above the item the advisor card is about; nil when off screen or not tracking.
    @Published private(set) var advisorAnchor: CGPoint?
    private var advisorAnchorItemIDs: [String] = []
    /// True while a horizontal surface is under the screen centre and placement can be confirmed.
    @Published private(set) var canPlace = false
    /// Called when the already-selected item is tapped again (highlights it everywhere).
    var onActivateSelectedItem: ((String) -> Void)?
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
    private var labelFrame = 0
    private var anchor: AnchorEntity?
    private var updateSubscription: (any Cancellable)?
    private var gestureRecognizers: [UIGestureRecognizer] = []
    private var itemPicker: ItemPicker?
    private let selectionOutline = ItemSelectionOutline()
    private var originalVisibility: [String: Bool] = [:]
    private var calloutEntity: Entity?
    private var ghost: AnchorEntity?
    private var ghostSize = SIMD2<Float>(0, 0)
    private var footprintExtents = SIMD3<Float>(repeating: 0.001)
    private var cutawayCache: (key: String, hidden: Set<String>)?
    private var previewPosition: SIMD3<Float>?
    private var footprintCenter = SIMD3<Float>.zero
    private var buildAnimator: BuildAnimator?
    private var choreographer: AnswerChoreographer?
    private var blueprint: BlueprintDetail?
    /// "7 doors" counting up while the voice answer lights items one by one; nil when idle.
    @Published private(set) var spotlight: Spotlight?

    struct Spotlight: Equatable {
        let text: String
        let color: UIColor
    }

    /// Colour legend rows for the current highlights ("Doors 11 . Windows 11"); empty unless kinds are known.
    var highlightLegend: [(style: KindStyle, count: Int)] {
        guard let manifest else { return [] }
        let kinds = highlightedItemIDs.compactMap { manifest.items[$0]?.kind }.filter { !$0.isEmpty }
        return KindColors.counts(of: kinds)
    }

    var scaleLabel: String { "1:\(Int((1 / scale).rounded()))" }
    var isSupported: Bool { ARWorldTrackingConfiguration.isSupported }
    var cutawayStoreys: [SceneManifest.Storey] { manifest.map { CutawayPolicy(manifest: $0).storeys } ?? [] }
    /// "Erdgeschoss · ±0.00" for the storey the cutaway is showing.
    var activeStoreyLabel: String? {
        guard let name = activeStorey, let storey = cutawayStoreys.first(where: { $0.name == name }) else { return nil }
        return BlueprintStyle.storeyLabel(name: name, elevation: storey.elevation_m ?? 0)
    }
    var canStepStoreyDown: Bool { storeyIndex.map { $0 > 0 } ?? false }
    var canStepStoreyUp: Bool { storeyIndex.map { $0 + 1 < cutawayStoreys.count } ?? false }
    private var storeyIndex: Int? { cutawayStoreys.firstIndex { $0.name == activeStorey } }

    /// Logical visibility updates immediately; the rendered entity may still be fading out.
    var visibleItemIDs: Set<String> {
        guard let manifest else { return [] }
        let cutaway = hiddenUSDNames(manifest: manifest)
        return Set(manifest.items.compactMap { id, item in
            !hiddenItemIDs.contains(id) && !cutaway.contains(item.usd_name)
                && (originalVisibility[item.usd_name] ?? true)
                && sceneIndex?.entitiesByUSDName[item.usd_name] != nil ? id : nil
        })
    }

    /// The cutaway is recomputed only when its inputs change; it is read every few frames for tags.
    private func hiddenUSDNames(manifest: SceneManifest) -> Set<String> {
        let key = "\(manifest.doc_id ?? "")|\(activeStorey ?? "")|\(showRoof)|\(highlightedItemIDs.joined(separator: ","))"
        if let cutawayCache, cutawayCache.key == key { return cutawayCache.hidden }
        let hidden = CutawayPolicy(manifest: manifest).hiddenUSDNames(activeStorey: activeStorey, showRoof: showRoof,
                                                                      keep: Set(highlightedItemIDs))
        cutawayCache = (key, hidden)
        return hidden
    }

    func attach(to view: ARView) {
        arView = view
        guard isSupported else {
            status = "Augmented reality requires a supported iPhone or iPad."
            return
        }
        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal]
        // Hands and people in front of the model must hide it (otherwise the model draws over your finger).
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.personSegmentationWithDepth) {
            configuration.frameSemantics.insert(.personSegmentationWithDepth)
        }
        // LiDAR phones: real-world mesh occludes the model too (table edges, objects in front).
        if ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) {
            configuration.sceneReconstruction = .mesh
            view.environment.sceneUnderstanding.options.insert(.occlusion)
        }
        view.session.run(configuration)
        updateSubscription = view.scene.subscribe(to: SceneEvents.Update.self) { [weak self] _ in
            self?.syncGestureScale()
            self?.updatePlacementPreview()
            self?.updateWalkGuide()
            self?.buildAnimator?.tick()
            self?.syncBuildState()
            self?.choreographer?.tick()
            self?.updateBlueprint()
            self?.updateAnswerLabels()
        }
    }

    func load(docID: String? = nil, url: URL?, manifestURL: URL? = nil, itemIDs: [String] = [],
              cameraTargetItemID: String? = nil) async {
        cancelBuild()
        resetPlacement()
        cancelVisibilityTransitions()
        highlightController?.clear()
        isLoaded = false
        isFixture = false
        isBundledDemo = false
        attribution = nil
        manifest = nil
        cutawayCache = nil
        sceneIdentity = SceneIdentity(requestedDocID: docID, manifest: nil)
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
            sceneIdentity = SceneIdentity(requestedDocID: docID, manifest: loaded.manifest,
                                          documentTitle: loaded.documentTitle, isBundled: loaded.isBundledDemo)
            attribution = loaded.attribution
            isBundledDemo = loaded.isBundledDemo
            activeDocID = loaded.manifest?.doc_id ?? (loaded.isFixture ? "fixture__ios" : docID)
            sceneIndex = SceneIndex(root: content)
            originalVisibility = sceneIndex?.entitiesByUSDName.mapValues(\.isEnabled) ?? [:]
            originalOpacity = sceneIndex?.entitiesByUSDName.mapValues {
                $0.components[OpacityComponent.self]?.opacity ?? 1
            } ?? [:]
            showRoof = false
            blueprint = nil
            if let manifest = loaded.manifest, let index = sceneIndex {
                BlueprintDetail.applyMaterials(manifest: manifest, index: index, content: content)
            }
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
            footprintExtents = size
            footprintCenter = localBounds.center
            let shape = ShapeResource.generateBox(size: size).offsetBy(translation: localBounds.center)
            container.components.set(CollisionComponent(shapes: [shape]))
            if let manifest = loaded.manifest, let index = sceneIndex {
                let detail = BlueprintDetail()
                detail.build(manifest: manifest, index: index, content: content)
                content.addChild(detail.root)
                blueprint = detail
                highlightController?.attachRoomPlates(detail.roomPlates)
            }
            container.scale = SIMD3(repeating: scale)
            model = container
            isFixture = loaded.isFixture
            isLoaded = true
            holoLog("scene ready doc=\(activeDocID ?? "-") items=\(manifest?.items.count ?? 0) bundled=\(isBundledDemo)")
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

    func trackAdvisorAnchor(itemIDs: [String]) {
        advisorAnchorItemIDs = itemIDs
        if itemIDs.isEmpty { advisorAnchor = nil } else { updateAdvisorAnchor() }
    }

    /// Projects the top centre of the card's items (the hidden door keeps its manifest box) to the screen.
    private func updateAdvisorAnchor() {
        guard isPlaced, let view = arView, let content, let manifest else { advisorAnchor = nil; return }
        let boxes = advisorAnchorItemIDs.compactMap { manifest.items[$0]?.bbox_m }
        guard let first = boxes.first else { advisorAnchor = nil; return }
        let local = SIMD3<Float>(first.center.x, first.maximum.y, first.center.z)
        let point = view.project(content.convert(position: local, to: nil))
        if let point, view.bounds.insetBy(dx: -40, dy: -40).contains(point) {
            if let old = advisorAnchor, abs(old.x - point.x) < 1.5, abs(old.y - point.y) < 1.5 { return }
            advisorAnchor = point
        } else {
            advisorAnchor = nil
        }
    }

    private func updateAnswerLabels() {
        if !advisorAnchorItemIDs.isEmpty { updateAdvisorAnchor() }
        if isPlaced, let view = arView { highlightController?.faceCamera(view.cameraTransform.rotation) }
        labelFrame = (labelFrame + 1) % 4
        guard labelFrame == 0, isPlaced, let view = arView else { return }
        highlightController?.layoutLabels(cameraTransform: view.cameraTransform.matrix,
                                         viewport: view.bounds, visibleItemIDs: visibleItemIDs,
                                         project: { view.project($0) })
    }

    func place(at point: CGPoint) {
        guard !isPlaced, let view = arView, model != nil,
              let hit = view.raycast(from: point, allowing: .existingPlaneGeometry,
                                     alignment: .horizontal).first else { return }
        if isWalking {
            guard let plane = hit.anchor as? ARPlaneAnchor, plane.classification == .floor else {
                status = "Move your device to detect the floor, then tap the floor to start walking."
                return
            }
        }
        finishPlacement(at: hit.worldTransform.columns.3.xyz)
    }

    /// Anchors the model where the ghost preview currently sits.
    func confirmPlacement() {
        guard !isPlaced, let position = previewPosition else { return }
        finishPlacement(at: position)
    }

    private func finishPlacement(at position: SIMD3<Float>) {
        holoLog("placement")
        guard let view = arView, let model else { return }
        removeGhost()
        // Keep scene Y vertical even if the estimated plane is slightly tilted.
        let anchor = AnchorEntity(world: position)
        anchor.addChild(model)
        view.scene.addAnchor(anchor)
        self.anchor = anchor
        if !isWalking { installTableGestures(on: view, model: model) }
        highlightController?.setLabelScale(isWalking ? 0.3 : 1)
        if !isWalking && !startBuild(model) && !UIAccessibility.isReduceMotionEnabled { playScanReveal(model) }
        isPlaced = true
        status = isWalking ? "Walk at 1:1. Select an item on the map to guide you."
            : "Tap an item for details. Pinch to scale, rotate with two fingers, or drag to move."
    }

    func tap(at point: CGPoint) {
        guard isPlaced else {
            if canPlace { confirmPlacement() } else { place(at: point) }
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
        if selectedItem?.id == itemID {
            onActivateSelectedItem?(itemID)
            return
        }
        let card = ItemCardModel(itemID: itemID, item: item)
        selectedItem = card
        selectionOutline.select(entity)
        showCallout(for: card, entity: entity)
    }

    /// Tap-to-hide: hides the selected item with the same fade as a voice edit. Returns the hidden id.
    @discardableResult
    func hideSelectedItem() -> String? {
        guard let id = selectedItem?.id, manifest?.items[id] != nil else { return nil }
        dismissSelectedItem()
        hiddenItemIDs.insert(id)
        applyCutaway(animated: true)
        return id
    }

    /// "Put it back" from the chrome: every hidden item returns.
    func restoreHiddenItems() {
        guard !hiddenItemIDs.isEmpty else { return }
        hiddenItemIDs = []
        applyCutaway(animated: true)
    }

    func dismissSelectedItem() {
        selectedItem = nil
        selectionOutline.clear()
        calloutEntity?.removeFromParent()
        calloutEntity = nil
    }

    private func showCallout(for card: ItemCardModel, entity: Entity) {
        calloutEntity?.removeFromParent()
        guard let content else { return }
        let bounds = entity.visualBounds(relativeTo: content)
        guard bounds.extents.x.isFinite, bounds.extents.y.isFinite else { return }
        let anchor = SIMD3<Float>(bounds.center.x, bounds.max.y, bounds.center.z)
        let callout = HologramCallout.make(item: card, anchor: anchor,
                                           unit: HighlightController.labelUnit(for: content),
                                           scale: isWalking ? 0.3 : 1)
        content.addChild(callout)
        calloutEntity = callout
    }

    // MARK: Placement preview and hologram effects

    /// A subtle translucent white footprint outline follows the screen-centre raycast until the model is placed.
    private func updatePlacementPreview() {
        guard !isPlaced, isLoaded, let view = arView, model != nil, view.bounds.width > 0 else {
            if canPlace { canPlace = false }
            removeGhost()
            return
        }
        let center = CGPoint(x: view.bounds.midX, y: view.bounds.midY)
        var hit = view.raycast(from: center, allowing: .existingPlaneGeometry, alignment: .horizontal).first
        if isWalking, let plane = hit?.anchor as? ARPlaneAnchor, plane.classification != .floor { hit = nil }
        if isWalking, hit != nil, !(hit?.anchor is ARPlaneAnchor) { hit = nil }
        guard let hit else {
            previewPosition = nil
            if canPlace { canPlace = false }
            ghost?.isEnabled = false
            return
        }
        let position = hit.worldTransform.columns.3.xyz
        previewPosition = position
        if !canPlace { canPlace = true }
        let extents = footprintExtents
        let size = SIMD2<Float>(max(extents.x * scale, 0.05), max(extents.z * scale, 0.05))
        if ghost == nil || simd_distance(size, ghostSize) > 0.001 { buildGhost(size: size) }
        ghost?.isEnabled = true
        ghost?.position = position
    }

    private func buildGhost(size: SIMD2<Float>) {
        removeGhost()
        ghostSize = size
        var outer = UnlitMaterial(color: .white)
        outer.blending = .transparent(opacity: .init(floatLiteral: 0.7))
        var inner = UnlitMaterial(color: .white)
        inner.blending = .transparent(opacity: .init(floatLiteral: 0.07))
        let border = max(min(size.x, size.y) * 0.008, 0.0015)
        let radius = min(size.x, size.y) * 0.06
        let ring = ModelEntity(mesh: .generatePlane(width: size.x, depth: size.y, cornerRadius: radius),
                               materials: [outer])
        let fill = ModelEntity(mesh: .generatePlane(width: size.x - border * 2, depth: size.y - border * 2,
                                                    cornerRadius: max(radius - border, 0)),
                               materials: [inner])
        fill.position.y = 0.0004
        let anchor = AnchorEntity(world: previewPosition ?? .zero)
        anchor.name = "placement-ghost"
        anchor.addChild(ring)
        anchor.addChild(fill)
        arView?.scene.addAnchor(anchor)
        ghost = anchor
    }

    private func removeGhost() {
        if let ghost { arView?.scene.removeAnchor(ghost) }
        ghost = nil
        previewPosition = nil
    }

    /// Scene-menu "Replay build": rebuilds the placed model step by step.
    func replayBuild() {
        guard isPlaced, !isWalking, let model else { return }
        cancelBuild()
        _ = startBuild(model)
    }

    var canReplayBuild: Bool { isLoaded && isPlaced && !isWalking }

    private func updateBlueprint() {
        guard let blueprint, let arView else { return }
        blueprint.update(activeStorey: activeStorey, hidden: !isPlaced || isBuildActive,
                         cameraPosition: arView.cameraTransform.translation,
                         time: ProcessInfo.processInfo.systemUptime)
    }

    private func cancelBuild() {
        buildAnimator?.dispose()
        buildAnimator = nil
        buildState = nil
        cancelChoreography()
    }

    /// True while the model is not fully built (playing, or scrubbed to an earlier step).
    private var isBuildActive: Bool { buildAnimator.map { !$0.isComplete } ?? false }

    private func syncBuildState() {
        let state = buildAnimator?.state
        if state != buildState { buildState = state }
    }

    /// Answer highlights stay fully grown whatever the step, as on the web.
    private var pinnedUSDNames: Set<String> {
        guard let manifest else { return [] }
        return Set(highlightedItemIDs.compactMap { manifest.items[$0]?.usd_name })
    }

    func playBuild() { buildAnimator?.play(); syncBuildState() }
    func pauseBuild() { buildAnimator?.pause(); syncBuildState() }
    func setBuildStep(_ index: Int) { buildAnimator?.setStep(index); syncBuildState() }
    func nextBuildStep() { buildAnimator?.next(); syncBuildState() }
    func previousBuildStep() { buildAnimator?.previous(); syncBuildState() }

    /// Ends a running voice choreography at its final pose and removes the dimming.
    private func cancelChoreography() {
        choreographer?.finish()
        choreographer?.restoreDim()
        choreographer = nil
        spotlight = nil
    }

    /// Voice answers: spin once, dim the rest, light the answer items one by one in reading order.
    private func startChoreography(itemIDs: [String]) {
        guard !UIAccessibility.isReduceMotionEnabled, isPlaced, !isBuildActive,
              let model, let content, let manifest, let index = sceneIndex,
              let highlights = highlightController else { return }
        let elevation = Dictionary(uniqueKeysWithValues: (manifest.storeys ?? []).compactMap { storey in
            storey.name.map { ($0, storey.elevation_m ?? 0) }
        })
        var entries: [AnswerChoreographer.Entry] = []
        var answerNames: Set<String> = []
        for id in Set(itemIDs) {
            guard let item = manifest.items[id], let entity = index.entitiesByUSDName[item.usd_name],
                  entity.isEnabled, highlights.litItemIDs.contains(id) else { continue }
            let center = item.bbox_m.map { SIMD2($0.center.x, $0.center.z) } ?? .zero
            entries.append(.init(
                item: .init(id: id, kind: item.kind, center: center,
                            elevation: item.storey.flatMap { elevation[$0] } ?? 0),
                entity: entity,
                color: item.kind.flatMap { $0.isEmpty ? nil : KindColors.style(for: $0).color }
                    ?? HighlightController.accentColor))
            answerNames.insert(item.usd_name)
        }
        guard !entries.isEmpty else { return }
        let visible = visibleItemIDs
        var dimmed: [(Entity, Float)] = []
        for (id, item) in manifest.items where visible.contains(id) && !answerNames.contains(item.usd_name) {
            guard let entity = index.entitiesByUSDName[item.usd_name], entity.isEnabled else { continue }
            dimmed.append((entity, originalOpacity[item.usd_name] ?? 1))
        }
        let kinds = entries.map(\.item.kind)
        let accent = entries.first?.color ?? HighlightController.accentColor
        let uniform = Set(kinds.map { KindColors.key(for: $0) }).count == 1
        let animator = AnswerChoreographer(
            container: model, content: content, pivot: footprintCenter, highlights: highlights,
            entries: entries, dimmed: dimmed, spin: !isWalking,
            unit: HighlightController.labelUnit(for: content),
            onCount: { [weak self] count in
                self?.spotlight = count == 0 ? nil
                    : Spotlight(text: AnswerChoreography.caption(count: count, kinds: kinds),
                                color: uniform ? accent : HighlightController.accentColor)
            },
            onFinish: { })
        choreographer = animator
        animator.begin()
    }

    /// Plan first, then the building rises out of it step by step (same steps as the web), with a scrubber. With
    /// Reduce Motion the finished model is shown at once and the scrubber still works. Returns false when there is
    /// nothing to build (no manifest).
    @discardableResult
    private func startBuild(_ model: ModelEntity) -> Bool {
        guard let manifest, let index = sceneIndex else { return false }
        let sequence = BuildSequence.make(manifest: manifest)
        guard !sequence.isEmpty else { return false }
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        let plan = reduceMotion ? nil : makePlanEntity(manifest: manifest)
        if let plan { model.addChild(plan) }
        let animator = BuildAnimator(sequence: sequence, entities: index.entitiesByUSDName, plan: plan,
                                     pinned: { [weak self] in self?.pinnedUSDNames ?? [] })
        buildAnimator = animator
        animator.begin(reduceMotion: reduceMotion)
        syncBuildState()
        return true
    }

    /// Flat plan drawn from the lowest storey's footprints, laid on the model's base at the model's scale.
    /// Plan plate drawn from the REAL bounds of the lowest storey's walls, doors, windows and columns, measured on
    /// the loaded entities in the placement container, so it matches the model's footprint and scale exactly.
    /// Returns nil (plate hidden) when nothing measurable is found.
    private func makePlanEntity(manifest: SceneManifest) -> Entity? {
        guard let container = model, let index = sceneIndex else { return nil }
        let lowest = CutawayPolicy(manifest: manifest).storeys.first?.name
        let kinds: Set<String> = ["wall", "door", "window", "column"]
        var rects: [BuildPlanImage.Rect] = []
        var floorY = Float.greatestFiniteMagnitude
        for item in manifest.items.values {
            guard let kind = item.kind, kinds.contains(kind), lowest == nil || item.storey == lowest,
                  let entity = index.entitiesByUSDName[item.usd_name] else { continue }
            let box = entity.visualBounds(relativeTo: container)
            guard box.extents.x.isFinite, box.extents.z.isFinite, box.extents.x > 0 || box.extents.z > 0 else { continue }
            rects.append(.init(kind: kind, minX: box.min.x, maxX: box.max.x, minZ: box.min.z, maxZ: box.max.z))
            floorY = min(floorY, box.min.y)
        }
        guard let image = BuildPlanImage.render(rects: rects), floorY.isFinite else { return nil }
        let minX = rects.map(\.minX).min()!, maxX = rects.map(\.maxX).max()!
        let minZ = rects.map(\.minZ).min()!, maxZ = rects.map(\.maxZ).max()!
        guard let mesh = BuildPlanImage.mesh(width: maxX - minX, depth: maxZ - minZ),
              let texture = try? TextureResource.generate(from: image, withName: nil,
                                                          options: .init(semantic: .color)) else { return nil }
        var material = UnlitMaterial()
        material.color = .init(tint: .white, texture: .init(texture))
        material.faceCulling = .none
        let entity = ModelEntity(mesh: mesh, materials: [material])
        entity.name = "build-plan"
        entity.position = [(minX + maxX) / 2, floorY + 0.01, (minZ + maxZ) / 2]
        return entity
    }

    /// Vertical sweep over about 0.8 s when the hologram appears.
    private func playScanReveal(_ model: Entity) {
        let target = model.transform
        var start = target
        start.scale = SIMD3(target.scale.x, max(target.scale.y * 0.02, 0.0001), target.scale.z)
        model.transform = start
        model.move(to: target, relativeTo: model.parent, duration: 0.8, timingFunction: .easeOut)
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
        cancelChoreography()
        highlightedItemIDs = itemIDs
        // Measure label positions against the full model before hiding the new cutaway.
        let visibility = sceneIndex?.entitiesByUSDName.mapValues(\.isEnabled) ?? [:]
        for item in manifest?.items.values ?? Dictionary<String, SceneManifest.Item>().values {
            sceneIndex?.entitiesByUSDName[item.usd_name]?.isEnabled = originalVisibility[item.usd_name] ?? true
        }
        var resolvedLabels = manifest?.items.compactMapValues(\.tag) ?? [:]
        resolvedLabels.merge(labels) { _, explicit in explicit }
        var captions: [String: String] = [:]
        var kinds: [String: String] = [:]
        var details: [String: String] = [:]
        for id in itemIDs {
            if let item = manifest?.items[id] {
                if let detail = BlueprintStyle.detail(for: item) { details[id] = detail }
                if let kind = item.kind, !kind.isEmpty { kinds[id] = kind }
                let text = item.kind.flatMap { $0.isEmpty ? nil : $0 } ?? item.name
                if let text { captions[id] = text }
            }
        }
        highlightController?.highlight(itemIDs: itemIDs, labels: resolvedLabels, captions: captions, kinds: kinds, details: details)
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
        if hasHiddenItems != !hiddenItemIDs.isEmpty { hasHiddenItems = !hiddenItemIDs.isEmpty }
        let hidden = hiddenUSDNames(manifest: manifest)
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
        var endedOnHighlight = true
        if let commands = answer.evidence.scene.commands, !commands.isEmpty {
            for command in commands { applySceneCommand(command) }
            if let last = commands.last { endedOnHighlight = last.op == .highlight }
        } else {
            setHighlights(answer.evidence.scene.highlight_item_ids,
                          cameraTargetItemID: answer.evidence.scene.camera_target_item_id,
                          labels: answer.highlightLabels)
        }
        // The wow moment follows whichever highlight the answer ended on.
        if endedOnHighlight, !highlightedItemIDs.isEmpty { startChoreography(itemIDs: highlightedItemIDs) }
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
        case .advisorCards, .ping, .ignored: return false
        }
        if !isLoaded, docID == requestedDocID {
            pendingLiveCommands.append(command)
            return true
        }
        guard docID == activeDocID else { return false }
        switch command {
        case .highlight(let request):
            setHighlights(request.itemIDs)
            // A question asked on another device (the laptop chat) gets the same spin and light-up.
            if !request.itemIDs.isEmpty { startChoreography(itemIDs: request.itemIDs) }
        case .edit(let edit):
            if let id = edit.edit_id, !appliedEditIDs.insert(id).inserted { return true }
            applySceneCommand(edit.command)
        case .state(let state):
            hiddenItemIDs = Set(state.hidden).intersection(Set(manifest?.items.keys.map { $0 } ?? []))
            let changed = Set(state.highlighted) != Set(highlightedItemIDs)
            setHighlights(state.highlighted, labels: state.labels)
            // Only a new answer animates; a reconnect re-sending the same state does not.
            if changed, !state.highlighted.isEmpty { startChoreography(itemIDs: state.highlighted) }
        case .advisorCards, .ping, .ignored: break
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
        cancelBuild()
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
        cancelBuild()
        removeGhost()
        canPlace = false
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
