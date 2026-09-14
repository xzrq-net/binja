use serde_json::{Value, json};
use std::{fs, path::Path, time::SystemTime};

pub fn status(state: &Path, installed: &str) -> Value {
    let now = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let cached = fs::read(state.join("cache/updates.json"))
        .ok()
        .and_then(|data| serde_json::from_slice::<Value>(&data).ok());
    if let Some(mut notice) = cached.filter(|n| {
        n["installed"] == installed
            && n["channel"] == "release-personal"
            && match n["status"].as_str() {
                Some("available" | "current") => {
                    n["latest_stable"].is_string()
                        && n["checked_at"].is_u64()
                        && n["expires_at"].is_u64()
                }
                Some("unknown") => n["error"].is_string(),
                _ => false,
            }
    }) {
        let stale = notice["checked_at"].as_u64().is_some_and(|t| t > now)
            || notice["expires_at"].as_u64().is_some_and(|t| t <= now);
        notice["stale"] = json!(stale);
        return notice;
    }
    json!({"installed":installed, "channel":"release-personal", "latest_stable":null,
        "status":"unknown", "checked_at":null, "expires_at":null, "stale":false,
        "error":"No matching stable release metadata cached"})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cached_states_staleness_and_invalid_data() {
        let state = std::env::temp_dir().join(format!("binja-updates-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(state.join("cache")).unwrap();
        let path = state.join("cache/updates.json");
        let now = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .unwrap()
            .as_secs();
        // Real releases from release-personal; model an older installation for
        // the available case instead of inventing a newer release.
        for (installed, outcome) in [("5.3.9757", "available"), ("6.0.10601", "current")] {
            let mut cached = json!({"installed":installed, "channel":"release-personal",
                "latest_stable":"6.0.10601 personal", "status":outcome,
                "checked_at":now, "expires_at":now+3600, "error":null});
            fs::write(&path, cached.to_string()).unwrap();
            let value = status(&state, installed);
            assert_eq!(value["status"], outcome);
            assert_eq!(value["stale"], false);
            assert_eq!(status(&state, "different build")["status"], "unknown");
            cached["expires_at"] = json!(0);
            fs::write(&path, cached.to_string()).unwrap();
            assert_eq!(status(&state, installed)["stale"], true);
        }
        fs::write(&path, r#"{"installed":"6.0.10601","channel":"release-personal","status":"unknown","error":"offline"}"#).unwrap();
        assert_eq!(status(&state, "6.0.10601")["error"], "offline");
        for malformed in ["broken", "[]", "null", r#"{"status":"available"}"#] {
            fs::write(&path, malformed).unwrap();
            assert_eq!(status(&state, "6.0.10601")["status"], "unknown");
        }
        fs::remove_dir_all(state).unwrap();
    }
}
