fn run_academia(args: Vec<String>) -> Result<String, String> {
    let output = std::process::Command::new("academia")
        .args(args)
        .output()
        .map_err(|error| format!("Academia CLI is unavailable: {error}"))?;
    if output.status.success() {
        String::from_utf8(output.stdout).map_err(|error| format!("Academia CLI returned invalid UTF-8: {error}"))
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

#[tauri::command]
fn academia_command(command: String, args: Vec<String>) -> Result<String, String> {
    let allowed = ["status", "courses", "tasks", "review", "activity", "workspace", "settings"];
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
        .invoke_handler(tauri::generate_handler![academia_command])
        .run(tauri::generate_context!())
        .expect("error while running Academia OS desktop");
}
