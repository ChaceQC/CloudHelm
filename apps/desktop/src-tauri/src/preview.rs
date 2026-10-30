use crate::{bridge, security};
use reqwest::Url;
use serde::Deserialize;
use std::time::Duration;
use tauri::{AppHandle, State, WebviewWindow};

#[cfg(windows)]
#[path = "preview_windows.rs"]
mod platform;

#[derive(Deserialize)]
struct Environment {
    environment_id: String,
    state: String,
    management_start_url: Option<String>,
    entry_origin: Option<String>,
    client_route: Option<String>,
}

#[derive(Clone)]
pub struct Target {
    pub management: Url,
    pub instance: Url,
}

fn target(environment: Environment, environment_id: &str) -> Result<Target, String> {
    let invalid = "preview_route_unavailable";
    if environment.environment_id != environment_id || environment.state != "ready"
        || environment.client_route.as_deref() != Some("tauri_windows_webview2") {
        return Err(invalid.into());
    }
    let management = Url::parse(environment.management_start_url.as_deref().ok_or(invalid)?)
        .map_err(|_| invalid)?;
    let instance = Url::parse(environment.entry_origin.as_deref().ok_or(invalid)?)
        .map_err(|_| invalid)?;
    if management.path() != format!("/preview/start/{environment_id}")
        || management.query().is_some() || management.fragment().is_some()
        || instance.path() != "/" || instance.query().is_some() || instance.fragment().is_some()
        || instance.origin() == management.origin()
        || !instance.host_str().is_some_and(|host| host.starts_with(&format!("{environment_id}.")))
        || [&management, &instance].iter().any(|url| url.scheme() != "https"
            || url.host_str().is_none() || url.port().is_some()
            || !url.username().is_empty() || url.password().is_some()) {
        return Err(invalid.into());
    }
    Ok(Target { management, instance })
}

// Only public, current Hub metadata crosses this boundary. The WebView authenticates itself.
#[tauri::command]
pub async fn preview_open(window: WebviewWindow, app: AppHandle, state: State<'_, bridge::HubState>,
                          generation: String, environment_id: String) -> Result<String, String> {
    security::trusted(&window)?;
    if !cfg!(windows) { return Err("preview_platform_unsupported".into()); }
    if environment_id.is_empty() || environment_id.len() > 160
        || !environment_id.bytes().all(|c| c.is_ascii_alphanumeric() || b"_-.:".contains(&c)) {
        return Err("preview_environment_invalid".into());
    }
    let session = bridge::selected_session(&state, &generation)?;
    let reply = bridge::bounded_reply(session.client.get(format!(
        "{}/api/preview-environments/{environment_id}", session.base))
        .bearer_auth(&session.token).header("X-CloudHelm-Api-Schema", security::API_SCHEMA)
        .timeout(Duration::from_secs(15)).send().await.map_err(|_| "hub_unreachable")?).await?;
    if reply.status != 200 { return Err("preview_route_unavailable".into()); }
    let target = target(serde_json::from_value(reply.body).map_err(|_| "response_schema_invalid")?,
        &environment_id)?;
    let (sender, mut receiver) = tauri::async_runtime::channel(1);
    let handle = app.clone();
    app.run_on_main_thread(move || {
        use tauri::Manager;
        let result = bridge::selected_session(&handle.state::<bridge::HubState>(), &generation)
            .and_then(|_| open(&handle, target));
        let _ = sender.try_send(result);
    }).map_err(|_| "preview_window_unavailable")?;
    receiver.recv().await.ok_or_else(|| "preview_window_unavailable".to_owned())?
}

#[cfg(windows)]
fn open(app: &AppHandle, target: Target) -> Result<String, String> { platform::open(app, target) }

#[cfg(not(windows))]
fn open(_app: &AppHandle, _target: Target) -> Result<String, String> {
    Err("preview_platform_unsupported".into())
}

#[tauri::command]
pub fn preview_close(window: WebviewWindow, app: AppHandle, label: String) -> Result<(), String> {
    security::trusted(&window)?;
    #[cfg(windows)]
    {
        app.clone().run_on_main_thread(move || platform::close(&app, &label))
            .map_err(|_| "preview_window_unavailable")?;
    }
    Ok(())
}

pub fn shutdown(app: &AppHandle) {
    #[cfg(windows)]
    platform::shutdown(app);
}
