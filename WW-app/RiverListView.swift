//
//  RiverListView.swift
//  WW-app
//
//  Created by Tyler Martin on 3/29/23.
//

import SwiftUI
import Amplify

struct RiverListView: View {
    let rivers: [River]
    @EnvironmentObject private var backend: Backend
    var body: some View {
        VStack {
            List(rivers) { river in
                NavigationLink(destination: RiverDetailView(river: river).environmentObject(backend)) {
                    VStack(alignment: .leading) {
                        Text(river.name)
                            .font(.headline)
                        Text(river.location)
                            .font(.subheadline)
                    }
                }
            }
            .navigationTitle("Rivers")
            SignInButton()
        }
        .onAppear {
            Task {
                do {
                    let session = try await Amplify.Auth.fetchAuthSession()
                    backend.isSignedIn = session.isSignedIn
                } catch {
                    print("Fetch auth session failed with error - \(error)")
                }
            }
        }
    }
}
struct SignInButton: View {
    var body: some View {
        Button(
            action: {
                Task { await Backend.shared.signIn() }
            },
            label: {
                HStack {
                    Image(systemName: "person.fill")
                        .scaleEffect(1.5)
                        .padding()
                    Text("Sign In")
                        .font(.largeTitle)
                }
                .padding()
                .foregroundColor(.white)
                .background(Color.green)
                .cornerRadius(30)
            }
        )
    }
}
struct SignOutButton : View {
    var body: some View {
        Button(
            action: {
                Task { await Backend.shared.signOut() }
            },
            label: { Text("Sign Out") }
        )
    }
}


struct RiverListView_Previews: PreviewProvider {
    static var previews: some View {
        RiverListView(rivers: [
            River(id: 1, name: "Upper Colorado River", location: "Colorado", snotelStationID: "1120", usgsSiteID: 09058000, reservoirSiteIDs: [1999, 2000, 2005]),
            River(id: 2, name: "Arkansas River by the Numbers", location: "Colorado", snotelStationID: "369", usgsSiteID: 07087050, reservoirSiteIDs: [100163, 100275])
        ])
    }
}



