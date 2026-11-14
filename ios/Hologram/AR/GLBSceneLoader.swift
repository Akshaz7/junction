import Foundation
import RealityKit
import UIKit

/// Builds a RealityKit entity tree from the server's `scene.glb` on the device, for scenes whose
/// `scene.usdz` is missing or stale (uploaded drawings: the server only has usd-core for the demo set).
/// Handles what the server's extruder writes: triangle meshes with POSITION and optional NORMAL, a node tree with
/// optional TRS or matrix transforms, and base-colour materials. The one embedded PNG (the plan image on the
/// `plan_floor` node) is decoded into a texture; if that fails the node is skipped and the scene still loads. Item nodes are renamed to the manifest's `usd_name` so `SceneIndex` works.
enum GLBSceneLoader {
    enum GLBError: LocalizedError {
        case notGLB, malformed(String)
        var errorDescription: String? {
            switch self {
            case .notGLB: "The 3D file is not a valid GLB."
            case .malformed(let why): "The 3D file could not be read (\(why))."
            }
        }
    }

    struct Document {
        let json: [String: Any]
        let bin: Data
    }

    /// Splits a GLB container into its JSON chunk and BIN chunk.
    static func parse(_ data: Data) throws -> Document {
        let bytes = [UInt8](data)
        func u32(_ at: Int) -> Int {
            Int(bytes[at]) | Int(bytes[at + 1]) << 8 | Int(bytes[at + 2]) << 16 | Int(bytes[at + 3]) << 24
        }
        guard bytes.count >= 20, u32(0) == 0x4654_6C67, u32(4) == 2 else { throw GLBError.notGLB }
        var offset = 12
        var json: [String: Any]?
        var bin = Data()
        while offset + 8 <= bytes.count {
            let length = u32(offset), type = u32(offset + 4)
            let start = offset + 8, end = start + length
            guard end <= bytes.count else { throw GLBError.malformed("truncated chunk") }
            if type == 0x4E4F_534A {
                json = try JSONSerialization.jsonObject(with: Data(bytes[start..<end])) as? [String: Any]
            } else if type == 0x004E_4942, bin.isEmpty {
                bin = Data(bytes[start..<end])
            }
            offset = end + ((4 - end % 4) % 4)
        }
        guard let json else { throw GLBError.malformed("no JSON chunk") }
        return Document(json: json, bin: bin)
    }

    @MainActor
    static func entity(from data: Data, nodeNames: [String: String]) throws -> Entity {
        try entity(from: parse(data), nodeNames: nodeNames)
    }

    /// `nodeNames` maps a glTF node name (the manifest item's `node`) to the item's `usd_name`.
    @MainActor
    static func entity(from doc: Document, nodeNames: [String: String]) throws -> Entity {
        let json = doc.json
        let nodes = json["nodes"] as? [[String: Any]] ?? []
        let meshes = json["meshes"] as? [[String: Any]] ?? []
        let sceneIndex = json["scene"] as? Int ?? 0
        let scenes = json["scenes"] as? [[String: Any]] ?? []
        let roots = (scenes.indices.contains(sceneIndex) ? scenes[sceneIndex]["nodes"] as? [Int] : nil)
            ?? Array(nodes.indices)
        guard !nodes.isEmpty, !meshes.isEmpty else { throw GLBError.malformed("no geometry") }

        var meshCache: [Int: [(MeshResource, PhysicallyBasedMaterial, Bool)]] = [:]
        func parts(of index: Int) throws -> [(MeshResource, PhysicallyBasedMaterial, Bool)] {
            if let cached = meshCache[index] { return cached }
            guard meshes.indices.contains(index) else { throw GLBError.malformed("bad mesh index") }
            var result: [(MeshResource, PhysicallyBasedMaterial, Bool)] = []
            for primitive in meshes[index]["primitives"] as? [[String: Any]] ?? [] {
                if let mode = primitive["mode"] as? Int, mode != 4 { continue }
                guard let attributes = primitive["attributes"] as? [String: Int],
                      let positionAccessor = attributes["POSITION"] else { continue }
                let positions = try floats(positionAccessor, components: 3, doc: doc)
                var descriptor = MeshDescriptor(name: meshes[index]["name"] as? String ?? "mesh")
                descriptor.positions = MeshBuffers.Positions(stride(from: 0, to: positions.count - 2, by: 3).map {
                    SIMD3(positions[$0], positions[$0 + 1], positions[$0 + 2])
                })
                if let normalAccessor = attributes["NORMAL"],
                   let normals = try? floats(normalAccessor, components: 3, doc: doc),
                   normals.count == positions.count {
                    descriptor.normals = MeshBuffers.Normals(stride(from: 0, to: normals.count - 2, by: 3).map {
                        SIMD3(normals[$0], normals[$0 + 1], normals[$0 + 2])
                    })
                }
                if let uvAccessor = attributes["TEXCOORD_0"], let uvs = try? floats(uvAccessor, components: 2, doc: doc),
                   uvs.count == positions.count / 3 * 2 {
                    // glTF has the UV origin top-left, RealityKit bottom-left.
                    descriptor.textureCoordinates = MeshBuffers.TextureCoordinates(
                        stride(from: 0, to: uvs.count - 1, by: 2).map { SIMD2(uvs[$0], 1 - uvs[$0 + 1]) })
                }
                let count = positions.count / 3
                let indices: [UInt32]
                if let indexAccessor = primitive["indices"] as? Int {
                    indices = try integers(indexAccessor, doc: doc)
                } else {
                    indices = (0..<UInt32(count)).map { $0 }
                }
                guard indices.count >= 3, indices.allSatisfy({ Int($0) < count }) else {
                    throw GLBError.malformed("bad indices")
                }
                descriptor.primitives = .triangles(Array(indices.prefix(indices.count - indices.count % 3)))
                let mesh = try MeshResource.generate(from: [descriptor])
                let (resolved, textured) = material(primitive["material"] as? Int, json: json, doc: doc)
                result.append((mesh, resolved, textured))
            }
            meshCache[index] = result
            return result
        }

        let root = Entity()
        var visiting = Set<Int>()
        func build(_ index: Int) throws -> Entity? {
            guard nodes.indices.contains(index), visiting.insert(index).inserted else { return nil }
            defer { visiting.remove(index) }
            let node = nodes[index]
            let rawName = node["name"] as? String ?? ""
            let entity = Entity()
            entity.name = nodeNames[rawName] ?? rawName
            entity.transform = transform(of: node)
            if let meshIndex = node["mesh"] as? Int {
                let built = try parts(of: meshIndex)
                // The plan image is optional decoration: without its texture the bare white plane is skipped.
                if rawName == "plan_floor", built.contains(where: { !$0.2 }) { return nil }
                for (mesh, material, _) in built {
                    entity.addChild(ModelEntity(mesh: mesh, materials: [material]))
                }
            }
            for child in node["children"] as? [Int] ?? [] {
                if let childEntity = try build(child) { entity.addChild(childEntity) }
            }
            return entity
        }
        for index in roots { if let entity = try build(index) { root.addChild(entity) } }
        guard !root.children.isEmpty else { throw GLBError.malformed("empty scene") }
        return root
    }

    /// `textured` is false when the material asked for a base-colour texture that could not be decoded.
    private static func material(_ index: Int?, json: [String: Any], doc: Document) -> (PhysicallyBasedMaterial, Bool) {
        var material = PhysicallyBasedMaterial()
        var rgba: [Double] = [0.7, 0.7, 0.7, 1]
        var doubleSided = false
        var textureIndex: Int?
        if let index, let list = json["materials"] as? [[String: Any]], list.indices.contains(index) {
            let entry = list[index]
            if let pbr = entry["pbrMetallicRoughness"] as? [String: Any],
               let factor = pbr["baseColorFactor"] as? [Double], factor.count == 4 { rgba = factor }
            textureIndex = ((entry["pbrMetallicRoughness"] as? [String: Any])?["baseColorTexture"] as? [String: Any])?["index"] as? Int
            doubleSided = entry["doubleSided"] as? Bool ?? false
        }
        let color = UIColor(red: rgba[0], green: rgba[1], blue: rgba[2], alpha: 1)
        var textured = true
        if let textureIndex {
            if let texture = texture(textureIndex, doc: doc) {
                material.baseColor = .init(tint: .white, texture: .init(texture))
            } else {
                textured = false
                material.baseColor = .init(tint: color)
            }
        } else {
            material.baseColor = .init(tint: color)
        }
        material.roughness = .init(floatLiteral: 0.9)
        material.metallic = .init(floatLiteral: 0)
        if rgba[3] < 0.99 { material.blending = .transparent(opacity: .init(floatLiteral: Float(rgba[3]))) }
        if doubleSided { material.faceCulling = .none }
        return (material, textured)
    }

    /// Decodes the PNG/JPEG embedded in the GLB for glTF texture `index`; nil when absent or undecodable.
    private static func texture(_ index: Int, doc: Document) -> TextureResource? {
        guard let textures = doc.json["textures"] as? [[String: Any]], textures.indices.contains(index),
              let source = textures[index]["source"] as? Int,
              let images = doc.json["images"] as? [[String: Any]], images.indices.contains(source),
              let viewIndex = images[source]["bufferView"] as? Int,
              let views = doc.json["bufferViews"] as? [[String: Any]], views.indices.contains(viewIndex),
              let length = views[viewIndex]["byteLength"] as? Int else { return nil }
        let start = views[viewIndex]["byteOffset"] as? Int ?? 0
        guard start >= 0, length > 0, start + length <= doc.bin.count,
              let image = UIImage(data: doc.bin.subdata(in: start..<start + length))?.cgImage else { return nil }
        return try? TextureResource.generate(from: image, options: .init(semantic: .color))
    }

    private static func transform(of node: [String: Any]) -> Transform {
        if let m = node["matrix"] as? [Double], m.count == 16 {
            let f = m.map(Float.init)
            return Transform(matrix: simd_float4x4(columns: (
                SIMD4(f[0], f[1], f[2], f[3]), SIMD4(f[4], f[5], f[6], f[7]),
                SIMD4(f[8], f[9], f[10], f[11]), SIMD4(f[12], f[13], f[14], f[15]))))
        }
        var t = Transform()
        if let v = node["translation"] as? [Double], v.count == 3 { t.translation = SIMD3(Float(v[0]), Float(v[1]), Float(v[2])) }
        if let q = node["rotation"] as? [Double], q.count == 4 {
            t.rotation = simd_quatf(ix: Float(q[0]), iy: Float(q[1]), iz: Float(q[2]), r: Float(q[3]))
        }
        if let s = node["scale"] as? [Double], s.count == 3 { t.scale = SIMD3(Float(s[0]), Float(s[1]), Float(s[2])) }
        return t
    }

    // MARK: accessors

    private static func view(_ accessorIndex: Int, doc: Document) throws
        -> (accessor: [String: Any], base: Int, stride: Int, count: Int) {
        guard let accessors = doc.json["accessors"] as? [[String: Any]], accessors.indices.contains(accessorIndex),
              let views = doc.json["bufferViews"] as? [[String: Any]] else { throw GLBError.malformed("bad accessor") }
        let accessor = accessors[accessorIndex]
        guard let viewIndex = accessor["bufferView"] as? Int, views.indices.contains(viewIndex),
              let count = accessor["count"] as? Int else { throw GLBError.malformed("accessor without data") }
        let bufferView = views[viewIndex]
        let base = (bufferView["byteOffset"] as? Int ?? 0) + (accessor["byteOffset"] as? Int ?? 0)
        return (accessor, base, bufferView["byteStride"] as? Int ?? 0, count)
    }

    private static func floats(_ index: Int, components: Int, doc: Document) throws -> [Float] {
        let v = try view(index, doc: doc)
        guard v.accessor["componentType"] as? Int == 5126 else { throw GLBError.malformed("not float") }
        let stride = v.stride > 0 ? v.stride : components * 4
        guard v.count == 0 || v.base + (v.count - 1) * stride + components * 4 <= doc.bin.count else {
            throw GLBError.malformed("accessor out of range")
        }
        var out: [Float] = []
        out.reserveCapacity(v.count * components)
        doc.bin.withUnsafeBytes { raw in
            for i in 0..<v.count {
                for c in 0..<components {
                    out.append(Float(bitPattern: raw.loadUnaligned(fromByteOffset: v.base + i * stride + c * 4, as: UInt32.self)))
                }
            }
        }
        return out
    }

    private static func integers(_ index: Int, doc: Document) throws -> [UInt32] {
        let v = try view(index, doc: doc)
        let size: Int
        switch v.accessor["componentType"] as? Int {
        case 5121: size = 1
        case 5123: size = 2
        case 5125: size = 4
        default: throw GLBError.malformed("bad index type")
        }
        let stride = v.stride > 0 ? v.stride : size
        guard v.count == 0 || v.base + (v.count - 1) * stride + size <= doc.bin.count else {
            throw GLBError.malformed("indices out of range")
        }
        var out: [UInt32] = []
        out.reserveCapacity(v.count)
        doc.bin.withUnsafeBytes { raw in
            for i in 0..<v.count {
                let at = v.base + i * stride
                switch size {
                case 1: out.append(UInt32(raw.load(fromByteOffset: at, as: UInt8.self)))
                case 2: out.append(UInt32(raw.loadUnaligned(fromByteOffset: at, as: UInt16.self)))
                default: out.append(raw.loadUnaligned(fromByteOffset: at, as: UInt32.self))
                }
            }
        }
        return out
    }
}
