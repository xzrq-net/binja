use crate::{render::text, resources::Resources};
use anyhow::{Context, Result, bail, ensure};
use serde_json::{Value, json};
use std::collections::HashSet;

fn resolve<'a>(records: &'a [Value], value: &str) -> Result<&'a Value> {
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
        let suffix = format!(".{value}");
        matches = records
            .iter()
            .filter(|r| text(r, "symbol").ends_with(&suffix))
            .collect();
    }
    ensure!(
        !matches.is_empty(),
        "No static declaration for {value:?}; the symbol is not in the static index. Native UI and C extension classes may exist outside it; inspect documentation with api paths."
    );
    ensure!(
        matches.len() == 1,
        "Ambiguous symbol; use a qualified name: {}",
        matches
            .iter()
            .map(|r| text(r, "symbol"))
            .collect::<Vec<_>>()
            .join(", ")
    );
    Ok(matches[0])
}

fn members(records: &[Value], value: &str, name_match: Option<&str>) -> Result<Value> {
    let class = resolve(records, value)?;
    ensure!(
        matches!(text(class, "kind"), "class" | "enum"),
        "{value:?} is a {}, not a class; use api show for its declaration.",
        text(class, "kind")
    );
    let pattern = name_match.map(|s| s.trim().to_lowercase());
    ensure!(
        pattern.as_deref() != Some(""),
        "Supply a nonempty --match substring."
    );
    let order = class["mro"]
        .as_array()
        .context("Class MRO missing; rebuild the API index")?;
    let mut seen = HashSet::new();
    let mut members = Vec::new();
    for owner in order {
        let owner = owner.as_str().context("API class MRO entry")?;
        let mut own: Vec<_> = records
            .iter()
            .filter(|r| {
                text(r, "symbol")
                    .rsplit_once('.')
                    .is_some_and(|(parent, _)| parent == owner)
            })
            .cloned()
            .collect();
        if let Some(values) = records
            .iter()
            .find(|r| text(r, "symbol") == owner)
            .and_then(|r| r["members"].as_array())
        {
            for value in values {
                let mut member = value.clone();
                member["symbol"] = json!(format!("{owner}.{}", text(value, "name")));
                member["kind"] = json!("enum_member");
                own.push(member);
            }
        }
        own.sort_by(|a, b| text(a, "symbol").cmp(text(b, "symbol")));
        for mut member in own {
            let name = text(&member, "symbol")
                .rsplit('.')
                .next()
                .unwrap()
                .to_owned();
            if !seen.insert(name.clone()) {
                continue;
            }
            if pattern
                .as_ref()
                .is_some_and(|p| !name.to_lowercase().contains(p))
            {
                continue;
            }
            let fields = member.as_object_mut().context("API member record")?;
            for key in [
                "alias",
                "doc",
                "bases",
                "mro",
                "unresolved_bases",
                "members",
            ] {
                fields.remove(key);
            }
            member["name"] = json!(name);
            member["owner"] = json!(owner);
            members.push(member);
        }
    }
    Ok(json!({
        "class": class["symbol"], "mro": class["mro"],
        "unresolved_bases": class["unresolved_bases"], "match": name_match,
        "total": members.len(), "total_members": seen.len(), "members": members,
    }))
}

pub fn query(
    resources: &Resources,
    operation: &str,
    value: &str,
    limit: usize,
    name_match: Option<&str>,
) -> Result<Value> {
    let config = resources.config()?;
    let vendor = text(&config, "vendor");
    let mut base = json!({"version":config["version"],"source":format!("{vendor}/python/binaryninja"),"docs":format!("{vendor}/api-docs")});
    if operation == "paths" {
        return Ok(base);
    }
    let index = resources.json("api-index.json")?;
    let records = index.as_array().context("API index must be an array")?;
    if operation == "members" {
        let listing = members(records, value, name_match)?;
        base.as_object_mut()
            .unwrap()
            .extend(listing.as_object().unwrap().clone());
        return Ok(base);
    }
    if operation == "show" {
        let record = resolve(records, value)?;
        for (key, val) in record.as_object().context("API record")? {
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
    let symbol = value["name"].as_str().unwrap_or(text(value, "symbol"));
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
    } else if value["kind"] == "enum_member" {
        let expression = value
            .get("value")
            .map(Value::to_string)
            .unwrap_or_else(|| text(value, "expression").into());
        format!("{symbol} = {expression}")
    } else {
        let signature = text(value, "signature");
        if let Some(args) = signature.find('(') {
            format!("{symbol}{}", &signature[args..])
        } else {
            symbol.into()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn members_use_mro_for_overrides_and_only_list_immediate_children() {
        let records = json!([
            {"symbol":"bn.Diamond", "kind":"class", "mro":["bn.Diamond","bn.Left","bn.Right","bn.Root"], "unresolved_bases":[]},
            {"symbol":"bn.Root.name", "kind":"property", "writable":true, "return_type":"str"},
            {"symbol":"bn.Left.zebra", "kind":"function", "signature":"zebra(self)"},
            {"symbol":"bn.Right.name", "kind":"property", "writable":false, "return_type":"int"},
            {"symbol":"bn.Diamond.Nested", "kind":"class", "signature":"class Nested()"},
            {"symbol":"bn.Diamond.Nested.hidden", "kind":"function"},
            {"symbol":"bn.Diamond.name_in_docs", "kind":"function", "signature":"name_in_docs(self, needle)", "doc":"needle"}
        ]);
        let records = records.as_array().unwrap();
        let result = members(records, "Diamond", None).unwrap();
        let rows = result["members"].as_array().unwrap();
        assert_eq!(
            rows.iter().map(|r| text(r, "name")).collect::<Vec<_>>(),
            ["Nested", "name_in_docs", "zebra", "name"]
        );
        assert_eq!(rows[3]["owner"], "bn.Right");
        assert_eq!(rows[3]["writable"], false);
        assert_eq!(rows[3]["return_type"], "int");
        let filtered = members(records, "bn.Diamond", Some(" NAME ")).unwrap();
        assert_eq!(filtered["total"], 2);
        assert_eq!(filtered["total_members"], 4);
        for pattern in ["needle", "bn.Right", "name*"] {
            assert_eq!(
                members(records, "Diamond", Some(pattern)).unwrap()["total"],
                0
            );
        }
    }
}
