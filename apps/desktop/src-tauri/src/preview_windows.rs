use super::Target;
use reqwest::Url;
use serde::Serialize;
use std::{cell::{Cell, RefCell}, collections::HashMap, fs, path::PathBuf, rc::Rc,
    sync::{atomic::{AtomicU64, Ordering}, Mutex}, thread, time::{Duration, SystemTime, UNIX_EPOCH}};
use tauri::{AppHandle, Emitter, Manager, WindowEvent, window::WindowBuilder};
use wry::{NewWindowResponse, PermissionResponse, WebContext, WebView, WebViewBuilder,
          WebViewBuilderExtWindows, WebViewExtWindows};
use webview2_com::{CoTaskMemPWSTR, WebResourceRequestedEventHandler, take_pwstr,
    Microsoft::Web::WebView2::Win32::COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL};

struct Container { view: WebView, _context: WebContext, directory: PathBuf }

thread_local! {
    static CONTAINERS: RefCell<HashMap<String, Container>> = RefCell::new(HashMap::new());
}
static NEXT_ID: AtomicU64 = AtomicU64::new(0);
static CLEANUPS: Mutex<Vec<thread::JoinHandle<()>>> = Mutex::new(Vec::new());

#[derive(Clone, Serialize)]
struct Cleanup { label: String, removed: bool }

fn remove_partition(app: AppHandle, label: String, directory: PathBuf) {
    let cleanup = thread::spawn(move || {
        // WebView2 releases its profile handles after controller.Close(), asynchronously.
        let mut removed = false;
        for _ in 0..50 {
            if !directory.exists() || fs::remove_dir_all(&directory).is_ok() {
                removed = true;
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let _ = app.emit_to("main", "preview-cleanup", Cleanup { label, removed });
    });
    CLEANUPS.lock().expect("preview cleanup lock").push(cleanup);
}

fn dispose(app: &AppHandle, label: &str) {
    let container = CONTAINERS.with(|containers| containers.borrow_mut().remove(label));
    if let Some(container) = container {
        // Starting this API is not a cleanup confirmation; actual directory removal is reported.
        let _ = container.view.clear_all_browsing_data();
        let directory = container.directory.clone();
        drop(container);
        remove_partition(app.clone(), label.to_owned(), directory);
    }
}

pub fn close(app: &AppHandle, label: &str) {
    if CONTAINERS.with(|containers| containers.borrow().contains_key(label)) {
        if let Some(window) = app.get_window(label) { let _ = window.close(); }
    }
}

pub fn shutdown(app: &AppHandle) {
    let labels = CONTAINERS.with(|containers| containers.borrow().keys().cloned().collect::<Vec<_>>());
    for label in labels { dispose(app, &label); }
    for cleanup in CLEANUPS.lock().expect("preview cleanup lock").drain(..) { let _ = cleanup.join(); }
}

pub fn open(app: &AppHandle, target: Target) -> Result<String, String> {
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|_| "preview_partition_unavailable")?.as_nanos();
    let label = format!("preview-{}-{stamp}-{}", std::process::id(), NEXT_ID.fetch_add(1, Ordering::Relaxed));
    let root = app.path().app_local_data_dir().map_err(|_| "preview_partition_unavailable")?
        .join("preview-sessions");
    fs::create_dir_all(&root).map_err(|_| "preview_partition_unavailable")?;
    let directory = root.join(&label);
    fs::create_dir(&directory).map_err(|_| "preview_partition_unavailable")?;
    let window = match WindowBuilder::new(app, &label).title("CloudHelm · 隔离预览")
        .inner_size(1100.0, 800.0).visible(false).build() {
        Ok(window) => window,
        Err(_) => {
            remove_partition(app.clone(), label, directory);
            return Err("preview_window_unavailable".into());
        }
    };
    let result = build(&window, target, directory.clone());
    let container = match result {
        Ok(container) => container,
        Err(error) => {
            let _ = window.destroy();
            remove_partition(app.clone(), label, directory);
            return Err(error);
        }
    };
    CONTAINERS.with(|containers| containers.borrow_mut().insert(label.clone(), container));
    let handle = app.clone();
    let closed_label = label.clone();
    window.on_window_event(move |event| {
        if matches!(event, WindowEvent::Destroyed) { dispose(&handle, &closed_label); }
    });
    if window.show().is_err() {
        dispose(app, &label);
        let _ = window.destroy();
        return Err("preview_window_unavailable".into());
    }
    Ok(label)
}

fn build(window: &tauri::Window, target: Target, directory: PathBuf) -> Result<Container, String> {
    let entered = Rc::new(Cell::new(false));
    let navigation_entered = entered.clone();
    let navigation_target = target.clone();
    let mut context = WebContext::new(Some(directory.clone()));
    let start = target.management.clone();
    // This is a raw Wry WebView: no Tauri protocols, scripts, capabilities or IPC handler.
    let view = WebViewBuilder::new_with_web_context(&mut context)
        .with_navigation_handler(move |value| {
            let Ok(url) = Url::parse(&value) else { return false; };
            if url.scheme() != "https" || !url.username().is_empty() || url.password().is_some() {
                return false;
            }
            if navigation_entered.get() { return url.origin() == navigation_target.instance.origin(); }
            if url == navigation_target.management { return true; }
            if url.origin() == navigation_target.instance.origin() && url.path() == "/__cloudhelm/redeem"
                && url.query().is_none() && url.fragment().is_none() {
                return true;
            }
            false
        })
        .with_new_window_req_handler(|_, _| NewWindowResponse::Deny)
        .with_permission_handler(|_| PermissionResponse::Deny)
        .with_download_started_handler(|_, _| false)
        .with_drag_drop_handler(|_| true)
        .with_clipboard(false).with_devtools(false)
        .with_browser_accelerator_keys(false).with_default_context_menus(false)
        .with_browser_extensions_enabled(false)
        .build(window).map_err(|_| "preview_window_unavailable")?;
    // Disable WebView2's own web-message channel and host objects before loading any document.
    unsafe {
        let settings = view.webview().Settings().map_err(|_| "preview_isolation_unavailable")?;
        settings.SetIsWebMessageEnabled(false).map_err(|_| "preview_isolation_unavailable")?;
        settings.SetAreHostObjectsAllowed(false).map_err(|_| "preview_isolation_unavailable")?;
        settings.SetAreDefaultScriptDialogsEnabled(false).map_err(|_| "preview_isolation_unavailable")?;
        let mut enabled = Default::default();
        settings.IsWebMessageEnabled(&mut enabled).map_err(|_| "preview_isolation_unavailable")?;
        if enabled.as_bool() { return Err("preview_isolation_unavailable".into()); }
    }
    request_guard(&view, target, entered)?;
    view.load_url(start.as_str()).map_err(|_| "preview_window_unavailable")?;
    Ok(Container { view, _context: context, directory })
}

fn request_guard(view: &WebView, target: Target, entered: Rc<Cell<bool>>) -> Result<(), String> {
    // NavigationStarting alone can cancel a commit after Chromium has sent its GET.
    // Stop disallowed requests before they reach any origin, including management after exchange.
    let wildcard = CoTaskMemPWSTR::from("*");
    let environment = view.environment();
    let resource = view.webview();
    let mut token = Default::default();
    unsafe {
        resource.AddWebResourceRequestedFilter(*wildcard.as_ref().as_pcwstr(),
            COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL).map_err(|_| "preview_isolation_unavailable")?;
        resource.add_WebResourceRequested(&WebResourceRequestedEventHandler::create(Box::new(move |_, args| {
            let Some(args) = args else { return Ok(()); };
            let request = args.Request()?;
            let mut uri = Default::default();
            let mut method = Default::default();
            request.Uri(&mut uri)?;
            request.Method(&mut method)?;
            let uri = take_pwstr(uri);
            let method = take_pwstr(method);
            let allowed = Url::parse(&uri).ok().is_some_and(|url| {
                if url.scheme() != "https" || !url.username().is_empty() || url.password().is_some() {
                    return false;
                }
                if entered.get() { return url.origin() == target.instance.origin(); }
                if url.origin() == target.instance.origin() && url.path() == "/__cloudhelm/redeem"
                    && url.query().is_none() && url.fragment().is_none() && method == "POST" {
                    // Even a failed or lost exchange requires closing and authenticating in a new container.
                    entered.set(true);
                    return true;
                }
                if url.origin() != target.management.origin() || url.query().is_some() || url.fragment().is_some() {
                    return false;
                }
                let id = target.management.path().trim_start_matches("/preview/start/");
                let revoke = url.path().strip_prefix("/api/preview-authorizations/")
                    .and_then(|path| path.strip_suffix("/revoke"))
                    .is_some_and(|id| !id.is_empty() && !id.contains('/'));
                (method == "GET" && (url == target.management
                    || url.path() == format!("/api/preview-environments/{id}/access-request")))
                    || (method == "POST" && (url.path() == format!("/api/preview-environments/{id}/access") || revoke))
            });
            if !allowed {
                let reason = CoTaskMemPWSTR::from("Forbidden");
                let headers = CoTaskMemPWSTR::from("Cache-Control: no-store\r\nContent-Type: text/plain\r\n");
                let response = environment.CreateWebResourceResponse(None, 403,
                    *reason.as_ref().as_pcwstr(), *headers.as_ref().as_pcwstr())?;
                args.SetResponse(&response)?;
            }
            Ok(())
        })), &mut token).map_err(|_| "preview_isolation_unavailable")?;
    }
    Ok(())
}
