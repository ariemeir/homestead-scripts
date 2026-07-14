import SwiftUI

struct ProjectsScreen: View {
    var body: some View {
        // TODO: list projects via ProjectStore.listProjectIDs(), show image
        // count/storage/last capture time, delete + drill into
        // ProjectDetailScreen (docs/scannercam_spec.md §10.2).
        List {
            Text("No projects yet.")
        }
        .navigationTitle("Projects")
    }
}

#Preview {
    NavigationStack { ProjectsScreen() }
}
