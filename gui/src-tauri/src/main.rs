// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod python_runtime;

use anyhow::Context;
use python_runtime::PythonRuntime;
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

/// Shared runtime guard that lives for the lifetime of the Tauri app.
struct AppState {
    python: Mutex<Option<PythonRuntime>>,
}

#[tauri::command]
fn get_api_base(state: tauri::State<'_, AppState>) -> Result<String, String> {
    let guard = state.python.lock().map_err(|e| e.to_string())?;
    guard
        .as_ref()
        .map(|rt| rt.base_url())
        .ok_or_else(|| "python runtime not started".to_string())
}

fn main() {
    if let Err(err) = run() {
        eprintln!("[ga-gui] fatal: {err:?}");
        std::process::exit(1);
    }
}

fn run() -> anyhow::Result<()> {
    let project_root = python_runtime::resolve_project_root()
        .context("failed to resolve project root containing launcher/api_server.py")?;
    let runtime = PythonRuntime::start(&project_root)
        .context("failed to start python launcher.api_server")?;
    let api_base = runtime.base_url();
    log::info!("python api server up at {api_base}");

    let state = AppState {
        python: Mutex::new(Some(runtime)),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_log::Builder::default().build())
        .manage(state)
        .invoke_handler(tauri::generate_handler![get_api_base])
        .setup(move |app| {
            // Inject API base into the webview before any user JS runs.
            let init = format!(
                "window.__GA_API_BASE__ = {};",
                serde_json::to_string(&api_base).expect("api base is valid json")
            );
            for (_label, window) in app.webview_windows() {
                window.eval(&init)?;
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .context("failed to build Tauri application")?
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<AppState>() {
                    if let Ok(mut guard) = state.python.lock() {
                        if let Some(rt) = guard.take() {
                            rt.shutdown();
                        }
                    }
                }
            }
        });

    Ok(())
}
