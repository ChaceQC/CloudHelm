#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;
mod journal;
mod preview;
mod security;
mod stream;

fn main() {
    tauri::Builder::default().manage(bridge::HubState::default())
        .invoke_handler(tauri::generate_handler![
            bridge::hub_transition, bridge::hub_connect, bridge::hub_request, bridge::hub_retry,
            bridge::hub_pending, bridge::hub_ack, stream::hub_subscribe,
            preview::preview_open, preview::preview_close,
        ])
        .build(tauri::generate_context!())
        .expect("CloudHelm desktop startup failed")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event { preview::shutdown(app); }
        });
}
