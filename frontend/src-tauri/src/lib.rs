use std::path::PathBuf;

fn academia_binary() -> PathBuf {
    if let Some(configured) = std::env::var_os("ACADEMIA_OS_CLI") {
        return PathBuf::from(configured);
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            let sibling = parent.join("academia");
            if sibling.is_file() {
                return sibling;
            }
        }
    }
    PathBuf::from("academia")
}

fn run_academia(args: Vec<String>) -> Result<String, String> {
    let output = std::process::Command::new(academia_binary())
        .args(args)
        .output()
        .map_err(|error| format!("Academia CLI is unavailable: {error}"))?;
    if output.status.success() {
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
fn academia_command(command: String, args: Vec<String>) -> Result<String, String> {
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
        "watch",
        "agents",
        "capabilities",
        "settings",
        "verify",
        "import",
        "domain",
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
    let mut cli_args = vec![command];
    cli_args.extend(args);
    run_academia(cli_args)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![academia_command])
        .run(tauri::generate_context!())
        .expect("error while running Academia OS desktop");
}
