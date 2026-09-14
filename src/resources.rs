use anyhow::{Context, Result, ensure};
use serde_json::Value;
use std::{
    env, fs,
    path::{Component, Path, PathBuf},
};

pub struct Resources {
    pub dir: PathBuf,
}
impl Resources {
    pub fn locate() -> Result<Self> {
        let installed = env::current_exe()?
            .parent()
            .context("Executable parent")?
            .join("../lib/binja");
        let dir = env::var_os("BINJA_RESOURCE_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                if installed.is_dir() {
                    installed
                } else {
                    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("binja")
                }
            });
        Ok(Self {
            dir: fs::canonicalize(&dir)
                .with_context(|| format!("Locate plugin resources at {}", dir.display()))?,
        })
    }
    pub fn config(&self) -> Result<Value> {
        self.json("build.json")
    }
    pub fn json(&self, name: &str) -> Result<Value> {
        Ok(serde_json::from_slice(&fs::read(self.dir.join(name)).with_context(|| format!("Read {}; for development copy build.json and api-index.json from result/lib/binja to binja/", self.dir.join(name).display()))?)?)
    }
}

pub fn absolute(path: impl AsRef<Path>) -> Result<PathBuf> {
    let path = path.as_ref();
    let expanded = if path == Path::new("~") {
        PathBuf::from(env::var_os("HOME").context("HOME is unset")?)
    } else if let Ok(tail) = path.strip_prefix("~/") {
        PathBuf::from(env::var_os("HOME").context("HOME is unset")?).join(tail)
    } else {
        path.to_path_buf()
    };
    let mut output = if expanded.is_absolute() {
        PathBuf::new()
    } else {
        env::current_dir()?
    };
    for component in expanded.components() {
        match component {
            Component::CurDir => (),
            Component::ParentDir => {
                output.pop();
            }
            other => {
                output.push(other);
                match fs::canonicalize(&output) {
                    Ok(resolved) => output = resolved,
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
                    Err(e) => {
                        return Err(e).with_context(|| format!("Resolve {}", output.display()));
                    }
                }
            }
        }
    }
    Ok(output)
}

pub fn state_path(path: &Path) -> Result<PathBuf> {
    let path = absolute(path)?;
    use std::os::unix::ffi::OsStrExt;
    ensure!(
        path.join("runtime/control.sock")
            .as_os_str()
            .as_bytes()
            .len()
            <= 107,
        "State path is too long for Unix sockets; choose a shorter --state-dir."
    );
    Ok(path)
}
