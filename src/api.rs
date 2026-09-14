use crate::{render::text, resources::Resources};
use anyhow::{Context, Result, bail};
use serde_json::{Value, json};

pub fn query(resources: &Resources, operation: &str, value: &str, limit: usize) -> Result<Value> {
    let config = resources.config()?;
    let vendor = text(&config, "vendor");
    let mut base = json!({"version":config["version"],"source":format!("{vendor}/python/binaryninja"),"docs":format!("{vendor}/api-docs")});
    if operation == "paths" {
        return Ok(base);
    }
    let index = resources.json("api-index.json")?;
    let records = index.as_array().context("API index must be an array")?;
    if operation == "show" {
        let mut matches: Vec<_> = records
            .iter()
            .filter(|r| {
                let alias = text(r, "alias");
                value == text(r, "symbol")
                    || value == alias
                    || Some(value) == alias.strip_prefix("binaryninja.")
            })
            .collect();
        if matches.is_empty() {
            matches = records
                .iter()
                .filter(|r| text(r, "symbol").ends_with(&format!(".{value}")))
                .collect();
        }
        if matches.is_empty() {
            bail!(
                "No static declaration for {value:?}; try api search. Inherited and native UI members may need direct documentation inspection (api paths)."
            );
        }
        if matches.len() != 1 {
            bail!(
                "Ambiguous symbol; use a qualified name: {}",
                matches
                    .iter()
                    .map(|r| text(r, "symbol"))
                    .collect::<Vec<_>>()
                    .join(", ")
            );
        }
        for (key, val) in matches[0].as_object().context("API record")? {
            if key != "alias" {
                base[key] = val.clone();
            }
        }
        return Ok(base);
    }
    let terms: Vec<_> = value.split_whitespace().map(str::to_lowercase).collect();
    if terms.is_empty() {
        bail!("Supply a nonempty API search query.");
    }
    let mut matches: Vec<_> = records
        .iter()
        .filter(|r| {
            let haystack = format!("{} {}", text(r, "symbol"), text(r, "doc")).to_lowercase();
            terms.iter().all(|t| haystack.contains(t))
        })
        .collect();
    matches.sort_by_key(|r| {
        let symbol = text(r, "symbol");
        let score = terms
            .iter()
            .filter(|t| symbol.to_lowercase().contains(t.as_str()))
            .count();
        (std::cmp::Reverse(score), symbol.len(), symbol)
    });
    base["total"] = json!(matches.len());
    base["matches"] = Value::Array(
        matches
            .into_iter()
            .take(limit)
            .map(|r| {
                let mut m = r.clone();
                m.as_object_mut().unwrap().remove("alias");
                m.as_object_mut().unwrap().remove("doc");
                m["summary"] = json!(text(r, "doc").lines().next().unwrap_or(""));
                m
            })
            .collect(),
    );
    Ok(base)
}

pub fn declaration(value: &Value) -> String {
    let symbol = text(value, "symbol");
    if value["kind"] == "property" {
        format!(
            "{symbol}: {} [property, {}]",
            value["return_type"].as_str().unwrap_or("unknown type"),
            if value["writable"] == true {
                "writable"
            } else {
                "read-only"
            }
        )
    } else if value["kind"] == "enum" {
        format!("{symbol} [enum]")
    } else {
        let signature = text(value, "signature");
        if let Some(args) = signature.find('(') {
            format!("{symbol}{}", &signature[args..])
        } else {
            symbol.into()
        }
    }
}
