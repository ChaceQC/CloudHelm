#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("CloudHelm 工程工作台窗口启动失败");
}
