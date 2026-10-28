import SwiftUI
import NoiseKit

/// Root. The survey until the renter has answered once; then two tabs, Score and Nearby, over one
/// store. The tab tint is greyscale so each screen keeps its one accent for its one thing.
struct ContentView: View {
    @State private var store = NoiseStore.forApp()

    var body: some View {
        Group {
            if store.hasAnswers {
                MainTabs(store: store)
            } else {
                SurveyView(store: store)
            }
        }
        .tint(Color(.label))
        .animation(.easeInOut(duration: 0.25), value: store.hasAnswers)
    }
}

struct MainTabs: View {
    let store: NoiseStore

    var body: some View {
        TabView {
            ScoreView(store: store)
                .tabItem { Label("Score", systemImage: "gauge.with.needle") }
            NearbyView(store: store)
                .tabItem { Label("Nearby", systemImage: "map") }
        }
        .task {
            if store.phase == .idle { await store.refresh() }
        }
    }
}

#Preview("App") {
    MainTabs(store: NoiseStore.preview()).tint(Color(.label))
}

#Preview("First launch") {
    ContentView()
}
