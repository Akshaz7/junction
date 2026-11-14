import Foundation

struct SceneCommand: Decodable, Equatable {
    enum Operation: String, Decodable { case highlight, hide, restore, reset, isolate }
    let op: Operation
    let item_ids: [String]
    let labels: [String: String]?
}

struct SceneEditEvent: Decodable, Equatable {
    let doc_id: String
    let edit_id: String?
    let command: SceneCommand

    private enum CodingKeys: String, CodingKey { case doc_id, edit_id }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        doc_id = try values.decode(String.self, forKey: .doc_id)
        edit_id = try values.decodeIfPresent(String.self, forKey: .edit_id)
        command = try SceneCommand(from: decoder)
    }
}

struct SceneStateEvent: Decodable, Equatable {
    let doc_id: String
    let hidden: [String]
    let highlighted: [String]
    let labels: [String: String]
}
