//! Kodo desktop shell.
//!
//! Phase 1 is a thin Tauri v2 wrapper around the shared React app. The orchestrator and the
//! Roslyn analyzer stay separate local processes; the webview only talks to the FastAPI API.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running Kodo");
}
