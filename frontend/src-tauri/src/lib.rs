use std::io::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use tauri::ipc::Channel;
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

static CHAT_FILE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn valid_run_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 80
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

fn stage_chat_payload(payload: &serde_json::Value) -> Result<std::path::PathBuf, String> {
    let body = serde_json::to_vec(payload).map_err(|error| format!("Invalid chat request: {error}"))?;
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
    Ok(path)
}

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

async fn run_academia_stream<F>(app: &tauri::AppHandle, args: Vec<String>, mut on_line: F) -> Result<(), String>
where
    F: FnMut(String) + Send,
{
    let shell = app.shell();
    let command = if let Ok(configured) = std::env::var("ACADEMIA_OS_CLI") {
        shell.command(configured)
    } else {
        match shell.sidecar("academia") {
            Ok(command) => command,
            Err(_) if cfg!(debug_assertions) => shell.command("academia"),
            Err(error) => return Err(format!("Bundled Academia CLI is unavailable: {error}")),
        }
    };
    let (mut receiver, _child) = command
        .args(args)
        .spawn()
        .map_err(|error| format!("Academia CLI could not start: {error}"))?;
    while let Some(event) = receiver.recv().await {
        match event {
            CommandEvent::Stdout(line) => on_line(String::from_utf8_lossy(&line).into_owned()),
            CommandEvent::Stderr(_) => {}
            CommandEvent::Error(error) => {
                return Err(format!("Academia CLI stream failed: {error}"))
            }
            CommandEvent::Terminated(payload) => {
                if payload.code != Some(0) {
                    let code = payload
                        .code
                        .map(|value| value.to_string())
                        .unwrap_or_else(|| "unknown".to_string());
                    return Err(format!("Academia CLI exited with status {code}"));
                }
                break;
            }
            _ => {}
        }
    }
    Ok(())
}

#[tauri::command]
async fn academia_command(app: tauri::AppHandle, command: String, args: Vec<String>) -> Result<String, String> {
    let allowed = [
        "status",
        "courses",
        "course",
        "today",
        "tasks",
        "task",
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
        "mcp-connections",
        "artifact",
        "account",
        "connectors",
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
    if command == "task" {
        let action = args.first().map(String::as_str).unwrap_or("");
        if !["list", "create", "update", "complete", "reopen"].contains(&action) {
            return Err("Unsupported Academia task action".to_string());
        }
    }
    if command == "mcp-connections" {
        let action = args.first().map(String::as_str).unwrap_or("");
        if !["list", "add", "add-remote", "authorize", "oauth-status", "oauth-cancel", "trust", "inspect", "grant", "call", "enable", "disable", "disconnect"].contains(&action) {
            return Err("Unsupported MCP connection action".to_string());
        }
    }
    if command == "account" {
        let action = args.first().map(String::as_str).unwrap_or("");
        let json_ok = args.last().map(String::as_str) == Some("--json");
        let core_len = if json_ok { args.len() - 1 } else { args.len() };
        let valid = match action {
            "status" | "logout" => core_len == 1,
            "login-cancel" => {
                core_len == 3
                    && args.get(1).map(String::as_str) == Some("--run-id")
                    && valid_run_id(args.get(2).map(String::as_str).unwrap_or(""))
            }
            _ => false,
        };
        if !valid {
            return Err("Unsupported Academia account action".to_string());
        }
    }
    if command == "connectors" {
        let provider = args.first().map(String::as_str).unwrap_or("");
        let action = args.get(1).map(String::as_str).unwrap_or("");
        let json_ok = args.last().map(String::as_str) == Some("--json");
        let core_len = if json_ok { args.len() - 1 } else { args.len() };
        let valid = provider == "google" && match action {
            "status" | "authorize" | "oauth-status" | "oauth-cancel" | "disconnect" => core_len == 2,
            "setup" => {
                core_len == 4
                    && args.get(2).map(String::as_str) == Some("--client-json")
                    && args.get(3).map(|value| !value.is_empty()).unwrap_or(false)
            }
            "calendar" => matches!(args.get(2).map(String::as_str), Some("list" | "propose-create" | "propose-update")),
            _ => false,
        };
        if !valid {
            return Err("Unsupported Academia connector action".to_string());
        }
    }
    let mut cli_args = vec![command];
    cli_args.extend(args);
    run_academia(&app, cli_args).await
}

#[tauri::command]
async fn academia_chat(app: tauri::AppHandle, payload: serde_json::Value) -> Result<String, String> {
    let path = stage_chat_payload(&payload)?;
    let result = run_academia(&app, vec!["chat".to_string(), "--input-file".to_string(), path.to_string_lossy().into_owned()]).await;
    let _ = std::fs::remove_file(path);
    result
}

#[tauri::command]
async fn academia_chat_stream(
    app: tauri::AppHandle,
    payload: serde_json::Value,
    run_id: String,
    on_event: Channel<serde_json::Value>,
) -> Result<(), String> {
    if !valid_run_id(&run_id) {
        return Err("Invalid chat run id".to_string());
    }
    let path = stage_chat_payload(&payload)?;
    let result = run_academia_stream(
        &app,
        vec![
            "chat-stream".to_string(),
            "--input-file".to_string(),
            path.to_string_lossy().into_owned(),
            "--run-id".to_string(),
            run_id,
        ],
        move |line| {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(line.trim()) {
                let _ = on_event.send(value);
            }
        },
    )
    .await;
    let _ = std::fs::remove_file(path);
    result
}

#[tauri::command]
async fn academia_chat_cancel(app: tauri::AppHandle, run_id: String) -> Result<serde_json::Value, String> {
    if !valid_run_id(&run_id) {
        return Err("Invalid chat run id".to_string());
    }
    let raw = run_academia(&app, vec!["chat-cancel".to_string(), "--run-id".to_string(), run_id, "--json".to_string()]).await?;
    serde_json::from_str(&raw).map_err(|error| format!("Invalid cancel response: {error}"))
}

#[tauri::command]
async fn academia_account_login_stream(
    app: tauri::AppHandle,
    run_id: String,
    on_event: Channel<serde_json::Value>,
) -> Result<(), String> {
    if !valid_run_id(&run_id) {
        return Err("Invalid account run id".to_string());
    }
    run_academia_stream(
        &app,
        vec![
            "account".to_string(),
            "login-stream".to_string(),
            "--run-id".to_string(),
            run_id,
        ],
        move |line| {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(line.trim()) {
                let _ = on_event.send(value);
            }
        },
    )
    .await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            academia_command,
            academia_chat,
            academia_chat_stream,
            academia_chat_cancel,
            academia_account_login_stream
        ])
        .run(tauri::generate_context!())
        .expect("error while running Academia OS desktop");
}
