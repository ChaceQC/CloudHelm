use reqwest::Url;
use std::time::Duration;
use tauri::WebviewWindow;

pub const API_SCHEMA: &str = "p1-hub-api-r1";
pub const MAX_BYTES: usize = 2 * 1024 * 1024;

pub fn trusted(window: &WebviewWindow) -> Result<(), String> {
    let url = window.url().map_err(|_| "window_not_trusted")?;
    let packaged = url.scheme() == "tauri" || (matches!(url.scheme(), "http" | "https")
        && url.host_str() == Some("tauri.localhost") && url.port().is_none());
    let development = cfg!(debug_assertions) && url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1") && url.port() == Some(14200);
    if window.label() != "main" || !(packaged || development) {
        return Err("window_not_trusted".into());
    }
    Ok(())
}

pub fn endpoint(value: &str, dev_loopback: bool) -> Result<String, String> {
    let url = Url::parse(value.trim()).map_err(|_| "hub_url_invalid")?;
    let local = matches!(url.host_str(), Some("127.0.0.1" | "[::1]" | "::1"));
    if url.host_str().is_none() || !url.username().is_empty() || url.password().is_some()
        || url.query().is_some() || url.fragment().is_some() || url.path() != "/"
        || !(url.scheme() == "https" || (url.scheme() == "http" && local && dev_loopback))
    {
        return Err("hub_https_or_explicit_loopback_required".into());
    }
    Ok(url.as_str().trim_end_matches('/').to_owned())
}

pub fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder().redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(5)).timeout(Duration::from_secs(35))
        .build().map_err(|_| "hub_client_unavailable".into())
}

pub fn entry(base: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new("com.cloudhelm.desktop", base).map_err(|_| "credential_store_unavailable".into())
}

pub fn credential(base: &str) -> Result<String, String> {
    entry(base)?.get_password().map_err(|_| "credential_not_available".into())
}

pub fn import_credential() -> Result<String, String> {
    let file = rfd::FileDialog::new().set_title("导入受保护的 Hub 会话凭据").pick_file()
        .ok_or("credential_import_cancelled")?;
    let metadata = std::fs::metadata(&file).map_err(|_| "credential_file_unavailable")?;
    if !metadata.is_file() || metadata.len() > 128 { return Err("credential_file_invalid".into()); }
    let content = std::fs::read_to_string(file).map_err(|_| "credential_file_invalid")?;
    let token = content.trim();
    if token.len() < 32 || token.len() > 100 || !token.bytes().all(|b| b.is_ascii_graphic()) {
        return Err("credential_file_invalid".into());
    }
    Ok(token.to_owned())
}

pub fn route_allowed(method: &str, route: &str) -> bool {
    if route.len() > 4096 || route.contains(['?', '#', '\\']) { return false; }
    let decoded: Result<Vec<_>, _> = route.split('/').map(|part|
        percent_encoding::percent_decode_str(part).decode_utf8().map(|v| v.into_owned())).collect();
    let Ok(decoded) = decoded else { return false; };
    let parts: Vec<_> = decoded.iter().map(String::as_str).collect();
    if parts.iter().skip(1).any(|p| p.is_empty() || p.chars().count() > 160 || matches!(*p, "." | "..")
        || p.chars().any(|c| c.is_control() || "/\\?#%".contains(c))) { return false; }
    match (method, parts.as_slice()) {
        ("GET", ["", "api", "auth", "me"] | ["", "api", "projects"]) => true,
        ("GET", ["", "api", "projects", _]) => true,
        ("GET", ["", "api", "projects", _, "snapshot"]) => true,
        ("GET", ["", "api", "tasks", _]) => true,
        ("GET", ["", "api", "tasks", _, "agent"]) => true,
        ("GET", ["", "api", "tasks", _, "agent-diff", _]) => true,
        ("GET", ["", "api", "projects", _, kind, _]) => matches!(*kind,
            "deployment-plans" | "releases" | "environments" | "environment-configurations" | "source-imports"),
        ("GET", ["", "api", "workspaces", _, "operations", _]) => true,
        ("GET", ["", "api", "development-environments", _, "operations", _]) => true,
        ("GET", ["", "api", "tasks", _, "builds", _]) => true,
        ("POST", ["", "api", "projects", _, kind]) => matches!(*kind,
            "tasks" | "reference-tasks" | "releases" | "environments"),
        ("POST", ["", "api", "tasks", _, action]) => matches!(*action, "start" | "cancel" | "reconcile" | "agent-runs"),
        ("POST", ["", "api", "projects", _, "deployment-plans", _, "approvals"]) => true,
        ("POST", ["", "api", "projects", _, "environments", _, action]) =>
            matches!(*action, "configurations" | "deployment-plans"),
        _ => false,
    }
}
