use crate::security::{self, API_SCHEMA, MAX_BYTES};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{sync::Mutex, time::Duration};
use tauri::{AppHandle, State, WebviewWindow};

pub struct Session {
    pub base: String,
    pub client: reqwest::Client,
    pub generation: String,
    pub account: String,
}

#[derive(Default)]
pub struct HubState {
    pub session: Mutex<Option<Session>>,
    pub stream: Mutex<Option<tauri::async_runtime::JoinHandle<()>>>,
}

#[derive(Serialize)]
pub struct Reply { pub status: u16, pub body: Value }

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HubRequest {
    pub method: String,
    pub route: String,
    pub body: Option<Value>,
    pub idempotency_key: Option<String>,
}

pub fn session(state: &HubState) -> Result<(String, reqwest::Client, String, String), String> {
    let guard = state.session.lock().map_err(|_| "session_unavailable")?;
    let value = guard.as_ref().ok_or("hub_disconnected")?;
    Ok((value.base.clone(), value.client.clone(), value.generation.clone(), value.account.clone()))
}

pub fn stop_stream(state: &HubState) {
    if let Ok(mut guard) = state.stream.lock() {
        if let Some(handle) = guard.take() { handle.abort(); }
    }
}

pub async fn bounded_reply(mut response: reqwest::Response) -> Result<Reply, String> {
    let status = response.status().as_u16();
    if response.headers().get("x-cloudhelm-api-schema").and_then(|v| v.to_str().ok()) != Some(API_SCHEMA) {
        return Err("api_schema_not_supported".into());
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "response_unconfirmed")? {
        if bytes.len() + chunk.len() > MAX_BYTES { return Err("response_too_large".into()); }
        bytes.extend_from_slice(&chunk);
    }
    let body: Value = serde_json::from_slice(&bytes).map_err(|_| "response_schema_invalid")?;
    Ok(Reply { status, body })
}

#[tauri::command]
pub async fn hub_connect(window: WebviewWindow, state: State<'_, HubState>, base_url: String,
                         import_credential: bool, dev_loopback: bool) -> Result<Value, String> {
    security::trusted(&window)?;
    stop_stream(&state);
    *state.session.lock().map_err(|_| "session_unavailable")? = None;
    let base = security::endpoint(&base_url, dev_loopback)?;
    let credential_base = base.clone();
    let token = tauri::async_runtime::spawn_blocking(move || {
        if import_credential { security::import_credential() } else { security::credential(&credential_base) }
    }).await.map_err(|_| "credential_store_unavailable")??;
    let client = security::client()?;
    let reply = bounded_reply(client.get(format!("{base}/api/auth/me"))
        .bearer_auth(&token).header("X-CloudHelm-Api-Schema", API_SCHEMA)
        .timeout(Duration::from_secs(15)).send().await.map_err(|_| "hub_unreachable")?).await?;
    if reply.status != 200 { return Err("authentication_failed".into()); }
    if import_credential {
        security::entry(&base)?.set_password(&token).map_err(|_| "credential_store_unavailable")?;
    }
    let generation = format!("{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| "clock_unavailable")?.as_nanos());
    let user = reply.body.get("user_id").and_then(Value::as_str).ok_or("response_schema_invalid")?;
    let account = format!("{base}|{user}");
    *state.session.lock().map_err(|_| "session_unavailable")? = Some(Session { base, client, generation, account });
    Ok(reply.body)
}

#[tauri::command]
pub fn hub_disconnect(window: WebviewWindow, state: State<'_, HubState>, forget: bool) -> Result<(), String> {
    security::trusted(&window)?;
    stop_stream(&state);
    let current = state.session.lock().map_err(|_| "session_unavailable")?.take();
    if forget {
        if let Some(current) = current {
            security::entry(&current.base)?.delete_credential().map_err(|_| "credential_delete_failed")?;
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn hub_request(window: WebviewWindow, app: AppHandle, state: State<'_, HubState>, request: HubRequest) -> Result<Reply, String> {
    security::trusted(&window)?;
    if !security::route_allowed(&request.method, &request.route) { return Err("route_not_allowed".into()); }
    let (base, client, generation, account) = session(&state)?;
    let token = security::credential(&base)?;
    let method = reqwest::Method::from_bytes(request.method.as_bytes()).map_err(|_| "method_invalid")?;
    let mut builder = client.request(method, format!("{base}{}", request.route)).bearer_auth(token)
        .header("X-CloudHelm-Api-Schema", API_SCHEMA).timeout(Duration::from_secs(15));
    if request.method == "POST" {
        let key = request.idempotency_key.as_deref().ok_or("idempotency_key_required")?;
        if key.is_empty() || key.len() > 160 || !key.bytes().all(|b| b.is_ascii_graphic()) {
            return Err("idempotency_key_invalid".into());
        }
        let body = request.body.as_ref().ok_or("command_body_required")?;
        if serde_json::to_vec(&body).map_err(|_| "command_invalid")?.len() > 65536 {
            return Err("command_too_large".into());
        }
        crate::journal::prepare(&app, &account, &request)?;
        builder = builder.header("Idempotency-Key", key).json(body);
    }
    let response = builder.send().await.map_err(|_| "request_unconfirmed")?;
    let reply = bounded_reply(response).await?;
    let confirmed = reply.body.get("command_id").and_then(Value::as_str).is_some()
        || reply.body.pointer("/task/command_id").and_then(Value::as_str).is_some()
        || reply.body.get("code").and_then(Value::as_str) == Some("request_schema_invalid");
    if request.method == "POST" && (200..500).contains(&reply.status) && confirmed {
        crate::journal::settle(&app, &account, request.idempotency_key.as_deref().unwrap_or(""))?;
    }
    if session(&state)?.2 != generation { return Err("session_changed".into()); }
    Ok(reply)
}

#[tauri::command]
pub fn hub_pending(window: WebviewWindow, app: AppHandle, state: State<'_, HubState>) -> Result<Vec<HubRequest>, String> {
    security::trusted(&window)?;
    crate::journal::load(&app, &session(&state)?.3)
}
