use anyhow::{Context, Result, ensure};
use serde_json::{Value, json};
use std::{
    fs::OpenOptions,
    io::Write,
    path::Path,
    process::{Command, Stdio},
};

fn run(state: &Path, config: &Value, tool: &str, args: &[&str]) -> Result<Vec<u8>> {
    let output = Command::new(config["timeout"].as_str().context("timeout path")?)
        .args([
            "--kill-after=1s",
            "2s",
            config[tool]
                .as_str()
                .with_context(|| format!("{tool} path"))?,
        ])
        .args(args)
        .env_clear()
        .env("XDG_RUNTIME_DIR", state.join("runtime"))
        .env("WAYLAND_DISPLAY", "wayland-0")
        .stdin(Stdio::null())
        .output()
        .with_context(|| format!("Run {tool}"))?;
    ensure!(
        output.status.success(),
        "{tool} exited {}: {}",
        output.status,
        String::from_utf8_lossy(&output.stderr).trim()
    );
    Ok(output.stdout)
}

fn capture(state: &Path, config: &Value) -> Result<(Vec<u8>, u32, u32)> {
    // Scale 1 makes click coordinates match the PNG's pixels.
    let png = run(state, config, "grim", &["-s", "1", "-"])?;
    ensure!(
        png.len() >= 24 && &png[..8] == b"\x89PNG\r\n\x1a\n" && &png[12..16] == b"IHDR",
        "grim returned an invalid PNG header"
    );
    let width = u32::from_be_bytes(png[16..20].try_into()?);
    let height = u32::from_be_bytes(png[20..24].try_into()?);
    ensure!(width > 0 && height > 0, "grim returned an empty output");
    Ok((png, width, height))
}

pub fn screenshot(state: &Path, config: &Value, path: Option<&str>) -> Result<Value> {
    let path = path.map(std::path::PathBuf::from).unwrap_or_else(|| {
        state
            .join("artifacts")
            .join(format!("screenshot-{}.png", uuid::Uuid::new_v4().simple()))
    });
    let (png, width, height) = capture(state, config)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .with_context(|| format!("Create screenshot {}", path.display()))?;
    file.write_all(&png)
        .with_context(|| format!("Write screenshot {}", path.display()))?;
    Ok(json!({"path":path,"width":width,"height":height}))
}

pub fn input(state: &Path, config: &Value, request: &Value) -> Result<Value> {
    if let Some(key) = request["key"].as_str() {
        // Establish the new virtual keyboard before its first press. Without
        // the empty modifier event, Qt sees that press only as an already-held
        // key in wl_keyboard.enter and ignores it.
        run(state, config, "wtype", &["-m", "shift", "-k", key])?;
        return Ok(json!({"action":"key","key":key}));
    }
    let x = request["x"].as_u64().context("Click x coordinate")?;
    let y = request["y"].as_u64().context("Click y coordinate")?;
    let (_, width, height) = capture(state, config)?;
    ensure!(
        x < width as u64 && y < height as u64,
        "Click ({x}, {y}) is outside the {width}x{height} screenshot"
    );
    // wlrctl moves relatively. On our single output, clamp to the top left
    // before moving to the screenshot pixel; no window or pointer queries.
    run(
        state,
        config,
        "wlrctl",
        &[
            "pointer",
            "move",
            &format!("-{width}"),
            &format!("-{height}"),
        ],
    )?;
    run(
        state,
        config,
        "wlrctl",
        &["pointer", "move", &x.to_string(), &y.to_string()],
    )?;
    run(state, config, "wlrctl", &["pointer", "click", "left"])?;
    Ok(json!({"action":"click","x":x,"y":y,"button":"left"}))
}
