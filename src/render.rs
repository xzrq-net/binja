use crate::api;
use anyhow::Result;
use serde_json::{Value, json};
use std::{
    io::{self, Write},
    path::Path,
};

pub fn text<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
fn seconds(v: &Value, k: &str) -> f64 {
    v[k].as_f64().unwrap_or(0.)
}
pub fn pending(v: &Value) -> bool {
    matches!(text(v, "status"), "queued" | "running" | "waiting_analysis")
}
pub fn quote(s: &str) -> String {
    if !s.is_empty()
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_@%+=:,./-".contains(&b))
    {
        s.into()
    } else {
        format!("'{}'", s.replace('\'', "'\"'\"'"))
    }
}
pub fn recovery(state: &Path, id: &str) -> String {
    format!(
        "binja --state-dir {} request {} --wait 30",
        quote(&state.to_string_lossy()),
        quote(id)
    )
}
pub fn receipt(v: &Value, existing: bool, json_mode: bool, verbose: bool) -> Result<()> {
    if json_mode {
        let mut event = json!({"event":"accepted"});
        for key in [
            "id",
            "status",
            "target_snapshot",
            "target_snapshot_stage",
            "phase",
            "elapsed_seconds",
            "queue_position",
            "waits_behind",
        ] {
            if let Some(value) = v.get(key) {
                event[key] = value.clone();
            }
        }
        eprintln!("{}", serde_json::to_string(&event)?);
    } else if !v["waits_behind"].is_null() {
        eprintln!(
            "{}: queued #{}  target snapshot {}  behind {}",
            if existing {
                "Existing request"
            } else {
                "Accepted"
            },
            v["queue_position"],
            text(&v["target_snapshot"], "handle"),
            text(v, "waits_behind")
        );
    }
    if verbose && !json_mode {
        eprintln!("Admission: {}", serde_json::to_string_pretty(v)?);
    }
    io::stderr().flush()?;
    Ok(())
}
fn target(v: &Value) -> String {
    let handle = text(&v["target_snapshot"], "handle");
    if handle.is_empty() {
        String::new()
    } else {
        format!("  target snapshot {handle}")
    }
}
pub fn row(v: &Value) -> String {
    let mut kind = text(v, "kind").to_string();
    if kind == "py" && !text(v, "filename").is_empty() {
        kind.push(' ');
        kind.push_str(
            &Path::new(text(v, "filename"))
                .file_name()
                .unwrap_or_default()
                .to_string_lossy(),
        );
    }
    let mut line = format!(
        "{} {}  {}{}",
        text(v, "id"),
        text(v, "status"),
        kind,
        target(v)
    );
    if v["status"] == "queued" {
        line.push_str(&format!(
            "  queued #{}  waiting {:.3}s",
            v["queue_position"],
            seconds(v, "queue_wait_seconds")
        ));
        if !v["waits_behind"].is_null() {
            line.push_str(&format!("  behind {}", text(v, "waits_behind")));
        }
    } else if pending(v) {
        line.push_str(&format!(
            "  {} {:.3}s",
            text(v, "phase"),
            seconds(v, "elapsed_seconds")
        ));
    } else {
        let execution = if v["execution_seconds"].is_null() {
            "not started".into()
        } else {
            format!("{:.3}s", seconds(v, "execution_seconds"))
        };
        line.push_str(&format!(
            "  queue {:.3}s / execution {execution}",
            seconds(v, "queue_wait_seconds")
        ));
    }
    if v["output_pruned"] == true {
        line.push_str("  inline output pruned");
    }
    if !text(v, "error").is_empty() {
        line.push_str(&format!("  {}", text(v, "error").replace('\n', " ")));
    }
    line
}
fn analysis(v: &Value) -> &str {
    match text(v, "analysis") {
        "IdleState" => "analysis complete",
        "InitialState" if v["view_type"] == "Raw" => "no analysis pipeline",
        other => other,
    }
}
fn output(v: &Value) -> Result<()> {
    for name in ["stdout", "stderr"] {
        let stream = &v[name];
        if !stream["artifact"].is_null() {
            println!(
                "{name}: {} ({} bytes)",
                text(stream, "artifact"),
                stream["bytes"]
            );
        } else if !text(stream, "text").is_empty() {
            let s = text(stream, "text");
            print!("{s}");
            if !s.ends_with('\n') {
                println!();
            }
        }
        if stream["truncated"] == true {
            println!("{name}: truncated at 1 MiB");
        }
    }
    if v["output_pruned"] == true {
        println!("Inline output pruned; retained artifacts follow.");
    }
    if let Some(result) = v.get("result") {
        if !result.is_null() {
            println!("{}", serde_json::to_string_pretty(result)?);
        }
    }
    if !v["result_artifact"].is_null() {
        println!(
            "Result: {} ({} bytes)",
            text(v, "result_artifact"),
            v["result_bytes"]
        );
    }
    if !v["error"].is_null() {
        println!("{}", v["traceback"].as_str().unwrap_or(text(v, "error")));
    }
    Ok(())
}

pub fn render(
    v: &Value,
    command: &str,
    json_mode: bool,
    verbose: bool,
    state: &Path,
) -> Result<()> {
    if json_mode {
        println!("{}", serde_json::to_string_pretty(v)?);
        return Ok(());
    }
    if !v["id"].is_null() {
        let kind = text(v, "kind");
        let result = &v["result"];
        if command == "cancel" {
            println!("Cancelled {}", text(v, "id"));
        } else if command == "open"
            && kind == "open"
            && v["status"] == "completed"
            && result.is_object()
        {
            println!(
                "Opened {}  {}  {}  {}  {:.3}s",
                text(result, "path"),
                text(result, "handle"),
                text(result, "view_type"),
                analysis(result),
                seconds(v, "elapsed_seconds")
            );
        } else if command == "save"
            && kind == "save"
            && v["status"] == "completed"
            && result["saved"].is_object()
        {
            println!(
                "Saved {}  {}  {:.3}s",
                text(&result["saved"], "path"),
                text(&result["target"], "handle"),
                seconds(v, "elapsed_seconds")
            );
        } else {
            if command == "request" || pending(v) {
                println!("{}", row(v));
            } else {
                println!(
                    "{}{}  {:.3}s",
                    match text(v, "status") {
                        "completed" => "Completed",
                        "failed" => "Failed",
                        "cancelled" => "Cancelled",
                        other => other,
                    },
                    target(v),
                    seconds(v, "elapsed_seconds")
                );
            }
            output(v)?;
        }
        if v["allow_incomplete"] == true {
            println!("Analysis: incomplete results explicitly allowed");
        }
        if v["client_wait_expired"] == true {
            println!(
                "Client wait expired; request {} is still {}.",
                text(v, "id"),
                text(v, "phase")
            );
        }
        if pending(v) {
            println!(
                "Retrieve with: {}",
                v["recovery_command"]
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| recovery(state, text(v, "id")))
            );
        }
    } else {
        match command {
            "targets" => {
                let targets = v.as_array().unwrap();
                for t in targets {
                    let dirty = if t["modified"] == true || t["analysis_changed"] == true {
                        "unsaved"
                    } else {
                        "clean"
                    };
                    println!(
                        "{}  {}  {}  {dirty}{}\n  {}",
                        text(t, "handle"),
                        text(t, "view_type"),
                        analysis(t),
                        if t["active"] == true {
                            "  [active]"
                        } else {
                            ""
                        },
                        text(t, "path")
                    );
                }
                if targets.is_empty() {
                    println!("No open targets. Use binja open PATH.");
                }
            }
            "requests" => {
                let rows = v["requests"].as_array().unwrap();
                for r in rows {
                    println!("{}", row(r));
                }
                if rows.is_empty() {
                    println!("No requests in this session.");
                }
                if v["finished_shown"] != v["finished_total"] {
                    println!(
                        "Showing {} of {} finished requests; use --all.",
                        v["finished_shown"], v["finished_total"]
                    );
                }
                if v["rejected_total"].as_u64().unwrap_or(0) > 0 {
                    let rejections = v["rejections"].as_array().unwrap();
                    println!(
                        "{} cap-rejected attempts; newest {}:",
                        v["rejected_total"],
                        rejections.len()
                    );
                    for r in rejections {
                        println!(
                            "{} not accepted  {}  running {}  {} queued",
                            text(r, "id"),
                            text(r, "filename"),
                            text(r, "running"),
                            r["queued"]
                        );
                    }
                }
            }
            "start" => println!(
                "{} Binary Ninja {}  GUI on a private Wayland compositor\nState: {}  generation {}",
                if v["reused"] == true {
                    "Reused"
                } else {
                    "Started"
                },
                text(v, "version"),
                text(v, "state_dir"),
                text(v, "generation")
            ),
            "status" => {
                if v["running"] == false {
                    println!("No running session  {}", text(v, "state_dir"));
                } else {
                    let rows = v["requests"].as_array().unwrap();
                    let queued = rows.iter().filter(|r| r["status"] == "queued").count();
                    println!(
                        "Running  {}  {} files ({} views)  {} running, {queued} queued",
                        text(v, "state_dir"),
                        v["file_count"],
                        v["view_count"],
                        rows.len() - queued
                    );
                    for r in rows {
                        println!("  {} {}", text(r, "id"), text(r, "status"));
                    }
                }
            }
            "stop" => println!(
                "Stopped  {}{}",
                text(v, "state_dir"),
                if v["discarded"] == true {
                    "; unsaved work discarded"
                } else {
                    ""
                }
            ),
            "api show" => {
                println!(
                    "{}\n{}:{}",
                    api::declaration(v),
                    text(v, "source"),
                    v["line"]
                );
                if let Some(members) = v["members"].as_array() {
                    for m in members {
                        println!(
                            "  {} = {}",
                            text(m, "name"),
                            m.get("value").map(Value::to_string).unwrap_or_else(|| text(
                                m,
                                "expression"
                            )
                            .into())
                        );
                    }
                }
                if !text(v, "doc").is_empty() {
                    println!("\n{}", text(v, "doc"));
                }
            }
            "api search" => {
                let matches = v["matches"].as_array().unwrap();
                if matches.len() as u64 != v["total"].as_u64().unwrap_or(0) {
                    println!(
                        "{} of {} matches; use --limit {} to show all",
                        matches.len(),
                        v["total"],
                        v["total"]
                    );
                } else {
                    println!("{} matches", v["total"]);
                }
                for m in matches {
                    println!("{}", api::declaration(m));
                    if !text(m, "summary").is_empty() {
                        println!("  {}", text(m, "summary"));
                    }
                }
            }
            _ => println!("{}", serde_json::to_string_pretty(v)?),
        }
    }
    if verbose {
        println!("Record:\n{}", serde_json::to_string_pretty(v)?);
    }
    Ok(())
}
