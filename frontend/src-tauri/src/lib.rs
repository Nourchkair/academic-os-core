use std::io::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use tauri_plugin_shell::ShellExt;

static CHAT_FILE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct CommandOutput {
    success: bool,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
}

fn run_system_cli(args: &[String]) -> Result<CommandOutput, String> {
    std::process::Command::new("academia")
        .args(args)
        .output()
        .map(|output| CommandOutput {
            success: output.status.success(),
            stdout: output.stdout,
            stderr: output.stderr,
        })
        .map_err(|error| format!("Academia CLI is unavailable: {error}"))
}

async fn run_academia(app: &tauri::AppHandle, args: Vec<String>) -> Result<String, String> {
    let output = if let Some(configured) = std::env::var_os("ACADEMIA_OS_CLI") {
        std::process::Command::new(configured)
            .args(&args)
            .output()
            .map(|output| CommandOutput {
                success: output.status.success(),
                stdout: output.stdout,
                stderr: output.stderr,
            })
            .map_err(|error| format!("Academia CLI is unavailable: {error}"))?
    } else {
        match app.shell().sidecar("academia") {
            Ok(command) => {
                match command.args(&args).output().await {
                    Ok(output) => CommandOutput {
                        success: output.status.success(),
                        stdout: output.stdout,
                        stderr: output.stderr,
                    },
                    Err(error) if cfg!(debug_assertions) => run_system_cli(&args).map_err(|_| {
                        format!("The bundled Academia CLI could not run in development: {error}")
                    })?,
                    Err(error) => return Err(format!("Bundled Academia CLI could not run: {error}")),
                }
            }
            Err(error) if cfg!(debug_assertions) => run_system_cli(&args)
                .map_err(|_| format!("Bundled Academia CLI is unavailable in development: {error}"))?,
            Err(error) => return Err(format!("Bundled Academia CLI is unavailable: {error}")),
        }
    };
    if output.success {
        String::from_utf8(output.stdout).map_err(|error| format!("Academia CLI returned invalid UTF-8: {error}"))
    } else {
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        Err(if stdout.is_empty() {
            stderr
        } else {
            stdout
        })
    }
}

#[tauri::command]
async fn academia_command(app: tauri::AppHandle, command: String, args: Vec<String>) -> Result<String, String> {
    let allowed = [
        "status",
        "courses",
        "course",
        "today",
        "tasks",
        "review",
        "activity",
        "workspace",
        "semester",
        "inbox",
        "process",
        "watch",
        "agents",
        "capabilities",
        "settings",
        "verify",
        "import",
        "domain",
        "history",
        "study",
        "library",
        "file-preview",
        "extract",
        "migration",
        "agent",
        "workflow",
        "artifact",
    ];
    if !allowed.contains(&command.as_str()) {
        return Err(format!("Unsupported Academia command: {command}"));
    }
    if command == "process"
        && (args.first().map(String::as_str) != Some("status")
            || args.len() > 2
            || args.iter().skip(1).any(|argument| argument != "--json"))
    {
        return Err("Only read-only processing status is available through the app".to_string());
    }
    let mut cli_args = vec![command];
    cli_args.extend(args);
    run_academia(&app, cli_args).await
}

#[tauri::command]
async fn academia_chat(app: tauri::AppHandle, payload: serde_json::Value) -> Result<String, String> {
    let body = serde_json::to_vec(&payload).map_err(|error| format!("Invalid chat request: {error}"))?;
    if body.len() > 48 * 1024 * 1024 {
        return Err("Chat request and attachments exceed 48 MB".to_string());
    }
    let sequence = CHAT_FILE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "academia-chat-{}-{sequence}.json",
        std::process::id()
    ));
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .map_err(|error| format!("Could not stage the chat request: {error}"))?;
    file.write_all(&body)
        .map_err(|error| format!("Could not stage the chat request: {error}"))?;
    drop(file);
    let result = run_academia(&app, vec!["chat".to_string(), "--input-file".to_string(), path.to_string_lossy().into_owned()]).await;
    let _ = std::fs::remove_file(path);
    result
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![academia_command, academia_chat])
        .run(tauri::generate_context!())
        .expect("error while running Academia OS desktop");
}
