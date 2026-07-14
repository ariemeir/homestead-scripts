import SwiftUI

struct ProjectDetailScreen: View {
    let projectID: String

    var body: some View {
        // TODO: image list, storage consumed, delete-project confirmation
        // requiring the project_id to be typed (docs/scannercam_spec.md §10.2, §10.4).
        Text(projectID)
            .navigationTitle(projectID)
    }
}

#Preview {
    NavigationStack { ProjectDetailScreen(projectID: "red_mug") }
}
