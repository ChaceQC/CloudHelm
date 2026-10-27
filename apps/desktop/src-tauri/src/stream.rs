use crate::{bridge::{self, HubState}, security::{self, API_SCHEMA}};
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, State, WebviewWindow};

#[derive(Clone, Serialize)]
struct Notice { subscription_id: String, kind: String, data: Value }

fn emit(app: &AppHandle, subscription_id: &str, kind: &str, data: Value) {
    let _ = app.emit_to("main", "hub-sync", Notice {
        subscription_id: subscription_id.into(), kind: kind.into(), data,
    });
}

fn identifier(value: &str) -> bool {
    !value.is_empty() && value.chars().count() <= 160 && !matches!(value, "." | "..")
        && !value.chars().any(|c| c.is_control() || "/\\?#%".contains(c))
}

#[tauri::command]
pub fn hub_subscribe(window: WebviewWindow, app: AppHandle, state: State<'_, HubState>,
                     project_id: String, stream_id: String, after: u64,
                     permission_revision: u64, subscription_id: String, generation: String) -> Result<(), String> {
    security::trusted(&window)?;
    if !identifier(&project_id) || !identifier(&stream_id) || !identifier(&subscription_id)
        || after > 9007199254740991 || permission_revision > 9007199254740991 {
        return Err("subscription_invalid".into());
    }
    let current = bridge::selected_session(&state, &generation)?;
    let mut url = reqwest::Url::parse(&format!("{}/api/projects/{project_id}/events", current.base))
        .map_err(|_| "subscription_invalid")?;
    url.query_pairs_mut().append_pair("stream_id", &stream_id).append_pair("after", &after.to_string())
        .append_pair("permission_revision", &permission_revision.to_string());
    let handle = tauri::async_runtime::spawn(async move {
        let result = consume(&app, &subscription_id, current.client.get(url).bearer_auth(current.token)
            .header("X-CloudHelm-Api-Schema", API_SCHEMA).header("Accept", "text/event-stream")).await;
        match result {
            Ok(()) => emit(&app, &subscription_id, "end", Value::Null),
            Err(code) => emit(&app, &subscription_id, code, Value::Null),
        }
    });
    // Tauri's runtime uses Tokio. Keep the abort handle, never a live DB/HTTP body in UI state.
    bridge::replace_stream(&state, &generation, handle)
}

async fn consume(app: &AppHandle, id: &str, request: reqwest::RequestBuilder) -> Result<(), &'static str> {
    let mut response = request.send().await.map_err(|_| "offline")?;
    match response.status().as_u16() {
        401 | 403 => return Err("access_revoked"),
        409 => return Err("reset"),
        200 => {},
        _ => return Err("offline"),
    }
    if response.headers().get("x-cloudhelm-api-schema").and_then(|v| v.to_str().ok()) != Some(API_SCHEMA) {
        return Err("incompatible");
    }
    let mut buffer = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "offline")? {
        buffer.extend_from_slice(&chunk);
        if buffer.len() > 131072 { return Err("incompatible"); }
        while let Some(end) = buffer.windows(2).position(|v| v == b"\n\n") {
            let frame: Vec<_> = buffer.drain(..end + 2).collect();
            let frame = std::str::from_utf8(&frame).map_err(|_| "incompatible")?;
            let kind = frame.lines().find_map(|l| l.strip_prefix("event: ")).unwrap_or("");
            let data = frame.lines().find_map(|l| l.strip_prefix("data: ")).ok_or("incompatible")?;
            let data: Value = serde_json::from_str(data).map_err(|_| "incompatible")?;
            if !matches!(kind, "batch" | "reset" | "access_revoked" | "unavailable") {
                return Err("incompatible");
            }
            emit(app, id, kind, data);
            if kind != "batch" { return Ok(()); }
        }
    }
    if !buffer.is_empty() { return Err("offline"); }
    Ok(())
}
