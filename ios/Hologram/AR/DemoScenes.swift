import Foundation

struct SceneAttribution: Decodable {
    let credit: String
    let licence: String
}

enum DemoScenes {
    struct Demo: Identifiable {
        let id: String
        let title: String
    }

    static let all = [
        Demo(id: "ifc_bench__ac20-arc", title: "AC20 · IFC building"),
        Demo(id: "cubicasa5k__colorful-11397", title: "CubiCasa5K · Floor plan")
    ]

    static func files(for docID: String, bundle: Bundle = .main) -> SceneRepository.Files? {
        guard all.contains(where: { $0.id == docID }),
              let model = bundle.url(forResource: "scene", withExtension: "usdz",
                                     subdirectory: "DemoScenes/\(docID)"),
              let manifest = bundle.url(forResource: "scene", withExtension: "json",
                                        subdirectory: "DemoScenes/\(docID)") else { return nil }
        return SceneRepository.Files(modelURL: model, manifestURL: manifest)
    }

    static func attribution(for docID: String?, bundle: Bundle = .main) -> SceneAttribution? {
        guard let docID, all.contains(where: { $0.id == docID }),
              let url = bundle.url(forResource: "doc", withExtension: "json",
                                   subdirectory: "DemoScenes/\(docID)"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(SceneAttribution.self, from: data)
    }
}
