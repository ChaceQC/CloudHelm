#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;
mod journal;
mod security;
mod stream;

fn main() {
    tauri::Builder::default().manage(bridge::HubState::default())
        .invoke_handler(tauri::generate_handler![
            bridge::hub_transition, bridge::hub_connect, bridge::hub_request, bridge::hub_retry,
            bridge::hub_pending, bridge::hub_ack, stream::hub_subscribe,
        ])
        .run(tauri::generate_context!())
        .expect("CloudHelm desktop startup failed");
}
