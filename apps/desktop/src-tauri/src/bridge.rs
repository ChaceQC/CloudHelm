use crate::security::{self, API_SCHEMA, MAX_BYTES};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{sync::Mutex, time::Duration};
use tauri::{AppHandle, State, WebviewWindow};

#[derive(Clone)]
pub struct Session {
    pub base: String,
    pub client: reqwest::Client,
    pub generation: String,
    pub account: String,
    pub token: String,
}

#[derive(Default)]
pub struct SessionState { pub generation: u64, pub current: Option<Session> }

#[derive(Default)]
pub struct HubState {
    pub session: Mutex<SessionState>,
    pub stream: Mutex<Option<tauri::async_runtime::JoinHandle<()>>>,
}

#[derive(Clone, Deserialize, Serialize)]
pub struct Reply { pub status: u16, pub body: Value }

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HubRequest {
    pub method: String,
    pub route: String,
    pub body: Option<Value>,
    pub idempotency_key: Option<String>,
}

#[derive(Serialize)]
pub struct Connected { identity: Value, generation: String }

pub fn selected_session(state: &HubState, generation: &str) -> Result<Session, String> {
    let guard = state.session.lock().map_err(|_| "session_unavailable")?;
    let value = guard.current.as_ref().ok_or("session_changed")?;
    if value.generation != generation { return Err("session_changed".into()); }
    Ok(value.clone())
}

// All stream replacement and connection transitions acquire these locks in this order.
pub fn replace_stream(state: &HubState, generation: &str,
                      handle: tauri::async_runtime::JoinHandle<()>) -> Result<(), String> {
    let guard = state.session.lock().map_err(|_| "session_unavailable")?;
    if guard.current.as_ref().map(|s| s.generation.as_str()) != Some(generation) {
        handle.abort();
        return Err("session_changed".into());
    }
    let mut stream = state.stream.lock().map_err(|_| "session_unavailable")?;
    if let Some(previous) = stream.replace(handle) { previous.abort(); }
    Ok(())
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

// A separate, serialized transition lets the UI invalidate an in-progress connect immediately.
#[tauri::command]
pub fn hub_transition(window: WebviewWindow, state: State<'_, HubState>, forget: bool) -> Result<String, String> {
    security::trusted(&window)?;
    let mut guard = state.session.lock().map_err(|_| "session_unavailable")?;
    guard.generation = guard.generation.checked_add(1).ok_or("session_unavailable")?;
    let current = guard.current.take();
    let mut stream = state.stream.lock().map_err(|_| "session_unavailable")?;
    if let Some(handle) = stream.take() { handle.abort(); }
    if forget {
        if let Some(current) = current {
            security::entry(&current.base)?.delete_credential().map_err(|_| "credential_delete_failed")?;
        }
    }
    Ok(guard.generation.to_string())
}

#[tauri::command]
pub async fn hub_connect(window: WebviewWindow, state: State<'_, HubState>, generation: String,
                         base_url: String, import_credential: bool, dev_loopback: bool) -> Result<Connected, String> {
    security::trusted(&window)?;
    {
        let guard = state.session.lock().map_err(|_| "session_unavailable")?;
        if guard.generation.to_string() != generation || guard.current.is_some() {
            return Err("session_changed".into());
        }
    }
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
    let user = reply.body.get("user_id").and_then(Value::as_str).filter(|s| !s.is_empty())
        .ok_or("response_schema_invalid")?;
    reply.body.get("session_id").and_then(Value::as_str).filter(|s| !s.is_empty())
        .ok_or("response_schema_invalid")?;
    let account = format!("{base}|{user}");
    let mut guard = state.session.lock().map_err(|_| "session_unavailable")?;
    if guard.generation.to_string() != generation || guard.current.is_some() {
        return Err("session_changed".into());
    }
    if import_credential {
        security::entry(&base)?.set_password(&token).map_err(|_| "credential_store_unavailable")?;
    }
    guard.current = Some(Session { base, client, generation: generation.clone(), account, token });
    Ok(Connected { identity: reply.body, generation })
}

fn validate(request: &HubRequest) -> Result<Option<(&str, &Value)>, String> {
    if !security::route_allowed(&request.method, &request.route) { return Err("route_not_allowed".into()); }
    if request.method != "POST" { return Ok(None); }
    let key = request.idempotency_key.as_deref().ok_or("idempotency_key_required")?;
    if key.is_empty() || key.len() > 160 || !key.bytes().all(|b| b.is_ascii_graphic()) {
        return Err("idempotency_key_invalid".into());
    }
    let body = request.body.as_ref().ok_or("command_body_required")?;
    if serde_json::to_vec(body).map_err(|_| "command_invalid")?.len() > 65536 {
        return Err("command_too_large".into());
    }
    Ok(Some((key, body)))
}

pub fn command_id(reply: &Reply) -> Option<&str> {
    reply.body.get("command_id").and_then(Value::as_str)
        .or_else(|| reply.body.pointer("/task/command_id").and_then(Value::as_str))
        .filter(|id| !id.is_empty())
}

fn confirmed(reply: &Reply) -> bool {
    (200..500).contains(&reply.status) && command_id(reply).is_some()
}

async fn send(app: &AppHandle, state: &HubState, session: &Session, request: &HubRequest,
              post: Option<(&str, &Value)>) -> Result<Reply, String> {
    let method = reqwest::Method::from_bytes(request.method.as_bytes()).map_err(|_| "method_invalid")?;
    let mut builder = session.client.request(method, format!("{}{}", session.base, request.route))
        .bearer_auth(&session.token).header("X-CloudHelm-Api-Schema", API_SCHEMA).timeout(Duration::from_secs(15));
    if let Some((key, body)) = post {
        builder = builder.header("Idempotency-Key", key).json(body);
    }
    selected_session(state, &session.generation)?;
    let response = builder.send().await.map_err(|_| "request_unconfirmed")?;
    let mut reply = bounded_reply(response).await?;
    if let Some((key, _)) = post.filter(|_| confirmed(&reply)) {
        reply = crate::journal::record(app, &session.account, key, &reply)?;
    }
    selected_session(state, &session.generation)?;
    Ok(reply)
}

#[tauri::command]
pub async fn hub_request(window: WebviewWindow, app: AppHandle, state: State<'_, HubState>,
                         generation: String, request: HubRequest) -> Result<Reply, String> {
    security::trusted(&window)?;
    let current = selected_session(&state, &generation)?;
    let post = validate(&request)?;
    if let Some((key, _)) = post { crate::journal::prepare(&app, &current.account, &request, key)?; }
    send(&app, &state, &current, &request, post).await
}

#[tauri::command]
pub async fn hub_retry(window: WebviewWindow, app: AppHandle, state: State<'_, HubState>,
                       generation: String, key: String) -> Result<Reply, String> {
    security::trusted(&window)?;
    let current = selected_session(&state, &generation)?;
    let request = crate::journal::get(&app, &current.account, &key)?;
    selected_session(&state, &generation)?;
    let post = validate(&request)?;
    // Reauthorize even a locally stored receipt before exposing it in a later session.
    send(&app, &state, &current, &request, post).await
}

#[tauri::command]
pub fn hub_pending(window: WebviewWindow, app: AppHandle, state: State<'_, HubState>,
                   generation: String) -> Result<Vec<HubRequest>, String> {
    security::trusted(&window)?;
    let current = selected_session(&state, &generation)?;
    let requests = crate::journal::load(&app, &current.account)?;
    selected_session(&state, &generation)?;
    Ok(requests)
}

#[tauri::command]
pub fn hub_ack(window: WebviewWindow, app: AppHandle, state: State<'_, HubState>,
               generation: String, key: String) -> Result<(), String> {
    security::trusted(&window)?;
    let guard = state.session.lock().map_err(|_| "session_unavailable")?;
    let current = guard.current.as_ref().filter(|s| s.generation == generation).ok_or("session_changed")?;
    crate::journal::settle(&app, &current.account, &key)
}
