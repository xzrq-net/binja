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

fn show(records: &[Value], value: &str) -> Result<Value> {
    let mut record = resolve(records, value)?.clone();
    record
        .as_object_mut()
        .context("API record")?
        .remove("alias");
    if record["kind"] == "class" {
        let listing = members(records, value, None)?;
        record["fields"] = Value::Array(
            listing["members"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|m| m["kind"] == "field")
                .cloned()
                .collect(),
        );
    }
    Ok(record)
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
        let record = show(records, value)?;
        base.as_object_mut()
            .unwrap()
            .extend(record.as_object().unwrap().clone());
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
    if value["kind"] == "field" {
        let default = value["default"]
            .as_str()
            .map(|expression| {
                let mut chars = expression.chars();
                let preview: String = chars.by_ref().take(160).collect();
                if chars.next().is_some() {
                    format!(" = {preview}… [full default: --json]")
                } else {
                    format!(" = {preview}")
                }
            })
            .unwrap_or_default();
        format!("{symbol}: {}{default} [field]", text(value, "annotation"))
    } else if value["kind"] == "class" {
        // Class signatures describe bases, not generated __init__ parameters.
        let signature = text(value, "signature");
        let bases = signature.find('(').map(|i| &signature[i..]).unwrap_or("");
        let bases = if bases == "()" { "" } else { bases };
        let mut result = format!("class {symbol}{bases}");
        if let Some(fields) = value["fields"].as_array().filter(|f| !f.is_empty()) {
            result.push(':');
            for field in fields {
                result.push_str(&format!("\n  {}", declaration(field)));
                let owner = text(field, "owner");
                if owner != text(value, "symbol") {
                    result.push_str(&format!(" [from {owner}]"));
                }
            }
        }
        result
    } else if value["kind"] == "property" {
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

    #[test]
    fn show_fields_uses_member_ownership_and_overrides() {
        let records = json!([
            {"symbol":"bn.Base", "kind":"class", "signature":"class Base()", "doc":"Base docs.", "mro":["bn.Base"], "unresolved_bases":[]},
            {"symbol":"bn.Child", "alias":"binaryninja.Child", "kind":"class", "signature":"class Child(Base)", "doc":"", "source":"example.py", "line":12, "mro":["bn.Child","bn.Base"], "unresolved_bases":[]},
            {"symbol":"bn.Base.offset", "kind":"field", "annotation":"int"},
            {"symbol":"bn.Base.value", "kind":"field", "annotation":"int"},
            {"symbol":"bn.Base.items", "kind":"field", "annotation":"list[int]", "default":"field(default_factory=list)"},
            {"symbol":"bn.Child.offset", "alias":"binaryninja.Child.offset", "kind":"field", "annotation":"int", "default":"0", "source":"example.py", "line":13},
            {"symbol":"bn.Child.value", "kind":"property", "return_type":"str", "writable":false},
            {"symbol":"bn.Child.method", "kind":"function", "signature":"method(self)"}
        ]);
        let records = records.as_array().unwrap();
        let filtered = members(records, "Child", Some(" OFFSET ")).unwrap();
        assert_eq!(filtered["total"], 1);
        assert_eq!(filtered["total_members"], 4);
        let row = &filtered["members"][0];
        assert_eq!(row["owner"], "bn.Child");
        assert_eq!(row["kind"], "field");
        assert_eq!(row["line"], 13);
        assert_eq!(declaration(row), "offset: int = 0 [field]");

        let result = show(records, "Child").unwrap();
        let fields = result["fields"].as_array().unwrap();
        assert_eq!(fields.len(), 2);
        assert_eq!(fields[0]["name"], "offset");
        assert_eq!(fields[1]["name"], "items");
        assert_eq!(fields[1]["owner"], "bn.Base");
        assert_eq!(result["doc"], "");
        assert_eq!(result["source"], "example.py");
        assert!(result.get("alias").is_none());
        assert_eq!(
            declaration(&result),
            "class bn.Child(Base):\n  offset: int = 0 [field]\n  items: list[int] = field(default_factory=list) [field] [from bn.Base]"
        );
        let base = show(records, "Base").unwrap();
        assert_eq!(base["doc"], "Base docs.");
        assert!(declaration(&base).starts_with("class bn.Base:\n"));
        assert_eq!(
            declaration(&show(records, "Child.offset").unwrap()),
            "bn.Child.offset: int = 0 [field]"
        );
    }

    #[test]
    fn field_declarations_distinguish_missing_defaults_from_source_expressions() {
        let mut field = json!({"name":"value", "kind":"field", "annotation":"Optional[int]"});
        assert_eq!(declaration(&field), "value: Optional[int] [field]");
        for expression in ["None", "0", "'text'", "core.max_confidence", "factory()"] {
            field["default"] = json!(expression);
            assert_eq!(
                declaration(&field),
                format!("value: Optional[int] = {expression} [field]")
            );
        }
        field["annotation"] = json!("ClassVar[int]");
        assert_eq!(
            declaration(&field),
            "value: ClassVar[int] = factory() [field]"
        );
        // Long operation tables must not dominate a member listing. Count
        // characters rather than bytes so source text stays valid Unicode.
        let prefix = "λ".repeat(160);
        field["default"] = json!(prefix);
        assert_eq!(
            declaration(&field),
            format!("value: ClassVar[int] = {prefix} [field]")
        );
        let full = format!("{prefix}x");
        field["default"] = json!(full);
        assert_eq!(
            declaration(&field),
            format!("value: ClassVar[int] = {prefix}… [full default: --json] [field]")
        );
        assert_eq!(field["default"], full);
    }

    #[test]
    fn enum_members_still_come_from_the_class_record() {
        let records = json!([
            {"symbol":"bn.Choice", "kind":"enum", "mro":["bn.Choice"], "unresolved_bases":[], "members":[{"name":"First", "expression":"1", "value":1}, {"name":"Computed", "expression":"auto()"}]}
        ]);
        let records = records.as_array().unwrap();
        let result = members(records, "Choice", None).unwrap();
        assert_eq!(result["total"], 2);
        assert_eq!(result["members"][0]["kind"], "enum_member");
        assert_eq!(result["members"][0]["owner"], "bn.Choice");
        assert_eq!(declaration(&result["members"][0]), "Computed = auto()");
        assert_eq!(declaration(&result["members"][1]), "First = 1");
        let shown = show(records, "Choice").unwrap();
        assert!(shown.get("fields").is_none());
        assert_eq!(shown["members"].as_array().unwrap().len(), 2);
    }
}
