use crate::{
    resources::{Resources, absolute},
    wire,
};
use anyhow::{Context, Result, bail, ensure};
use serde_json::{Value, json};
use socket2::SockAddr;
use std::{
    fs::{self, File, OpenOptions},
    os::{
        fd::AsRawFd,
        unix::{
            fs::{DirBuilderExt, MetadataExt, PermissionsExt, symlink},
            process::CommandExt,
        },
    },
    path::Path,
    process::{Child, Command, Stdio},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread::sleep,
    time::{Duration, Instant},
};

const ENDPOINTS: [&str; 4] = ["rpc.sock", "control.sock", "wayland-0", "wayland-0.lock"];
fn lock_file(state: &Path, create: bool) -> Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(create)
        .truncate(false)
        .open(state.join("runtime/lock"))?)
}
fn try_lock(file: &File) -> Result<bool> {
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
        return Ok(true);
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::EWOULDBLOCK) {
        Ok(false)
    } else {
        Err(error.into())
    }
}
fn prepare(state: &Path) -> Result<()> {
    for relative in [
        "",
        "bn",
        "bn/plugins",
        "config",
        "cache",
        "data",
        "runtime",
        "tmp",
        "logs",
        "artifacts",
    ] {
        let dir = state.join(relative);
        ensure!(
            !dir.is_symlink(),
            "State directory must not be a symlink: {}",
            dir.display()
        );
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&dir)?;
        ensure!(
            dir.metadata()?.uid() == unsafe { libc::getuid() },
            "State directory has a different owner: {}",
            dir.display()
        );
        fs::set_permissions(dir, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}
fn unlink(path: &Path) -> Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}
fn atomic_json(path: &Path, value: &Value) -> Result<()> {
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, serde_json::to_vec_pretty(value)?)?;
    fs::rename(tmp, path)?;
    Ok(())
}
fn retire_artifacts(state: &Path) -> Result<()> {
    for entry in fs::read_dir(state.join("artifacts"))? {
        let entry = entry?;
        if entry.file_type()?.is_dir() {
            fs::remove_dir_all(entry.path())?;
        } else {
            fs::remove_file(entry.path())?;
        }
    }
    Ok(())
}
fn detached(command: &mut Command) {
    // No allocation or Rust runtime work is performed between fork and exec.
    unsafe {
        command.pre_exec(|| {
            if libc::setsid() < 0 {
                Err(std::io::Error::last_os_error())
            } else {
                Ok(())
            }
        });
    }
    command.stdin(Stdio::null());
}
// ESRCH is the only proof that the owned group is gone.
fn signal_group(group: i32, signal: i32) -> Result<bool> {
    if unsafe { libc::killpg(group, signal) } == 0 {
        return Ok(true);
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        Ok(false)
    } else {
        Err(error.into())
    }
}
fn terminate(child: &mut Child) -> Result<()> {
    let group = child.id() as i32;
    signal_group(group, libc::SIGTERM)?;
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        // Reap the leader through Child first, then any orphan descendants
        // adopted by this supervisor's subreaper. Zombies keep a group alive.
        if child.try_wait()?.is_some() {
            loop {
                let reaped = unsafe { libc::waitpid(-group, std::ptr::null_mut(), libc::WNOHANG) };
                if reaped >= 0 {
                    if reaped == 0 {
                        break;
                    }
                    continue;
                }
                let error = std::io::Error::last_os_error();
                match error.raw_os_error() {
                    Some(libc::EINTR) => continue,
                    Some(libc::ECHILD) => break,
                    _ => return Err(error.into()),
                }
            }
        }
        if !signal_group(group, 0)? {
            return Ok(());
        }
        if Instant::now() >= deadline {
            signal_group(group, libc::SIGKILL)?;
        }
        sleep(Duration::from_millis(50));
    }
}

pub fn status(state: &Path) -> Result<Value> {
    if !state.join("runtime/lock").exists() {
        ensure!(
            !state.join("runtime/rpc.sock").exists(),
            "Session endpoint exists without an ownership lock; inspect {}/logs",
            state.display()
        );
        return Ok(json!({"running":false,"state_dir":state}));
    }
    let lock = lock_file(state, false)?;
    if try_lock(&lock)? {
        return Ok(json!({"running":false,"state_dir":state}));
    }
    let mut value = wire::rpc(state, "status", json!({}), false, 5.)?;
    value["running"] = json!(true);
    let targets = value["targets"].as_array().context("Status targets")?;
    let mut files = std::collections::HashSet::new();
    for target in targets {
        files.insert(target["file_id"].to_string());
    }
    let views = targets.len();
    value["file_count"] = json!(files.len());
    value["view_count"] = json!(views);
    Ok(value)
}

pub fn start(state: &Path, license: Option<&Path>, resources: &Resources) -> Result<Value> {
    prepare(state)?;
    let busy = {
        let lock = lock_file(state, true)?;
        !try_lock(&lock)?
    };
    let mut process = None;
    if !busy {
        let license = absolute(license.unwrap_or(Path::new("~/.binaryninja/license.dat")))?;
        ensure!(
            license.is_file(),
            "License not found: {}. Pass start --license PATH.",
            license.display()
        );
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(state.join("logs/supervisor.log"))?;
        let mut command = Command::new(std::env::current_exe()?);
        command
            .arg("__supervisor")
            .arg(state)
            .arg(&license)
            .env("BINJA_RESOURCE_DIR", &resources.dir)
            .stdout(log.try_clone()?)
            .stderr(log);
        detached(&mut command);
        process = Some(command.spawn().context("Start session supervisor")?);
    }
    let mut deadline = Instant::now() + Duration::from_secs(70);
    let mut exited = None;
    let mut last_error = String::from("receiver has not started");
    while Instant::now() < deadline {
        // A competing supervisor may win the flock after our preliminary check.
        // Both losers and callers arriving during initialization wait for it.
        let exit = match process.as_mut() {
            Some(child) => child.try_wait()?,
            None => None,
        };
        if exit.is_some() && exited.is_none() {
            exited = exit;
            // A loser may exit before the winner's receiver is ready, but an
            // unsuccessful launch should not consume the full startup timeout.
            deadline = deadline.min(Instant::now() + Duration::from_secs(5));
        }
        // Do not probe flock while supervisors are competing to acquire it:
        // a transient status lock could itself make a supervisor lose.
        match wire::rpc(state, "status", json!({}), false, 1.) {
            Ok(_) => {
                let mut value = status(state)?;
                ensure!(value["running"] == true, "Session stopped during startup");
                let config = resources.config()?;
                ensure!(
                    value["version"]
                        .as_str()
                        .unwrap_or("")
                        .split_whitespace()
                        .next()
                        == config["version"].as_str(),
                    "Running Binary Ninja version differs from this CLI; stop it before upgrading."
                );
                value["reused"] = json!(busy || exit.is_some());
                return Ok(value);
            }
            Err(error) => {
                last_error = match exit {
                    Some(exit) => format!("spawned supervisor exited ({exit}); {error:#}"),
                    None => format!("{error:#}"),
                };
            }
        }
        sleep(Duration::from_millis(200));
    }
    if let Some(exit) = exited {
        bail!(
            "Session startup exited ({exit}); inspect {}/logs.",
            state.display()
        );
    }
    bail!("Startup wait timed out: {last_error}; use status or stop --force to recover.")
}

pub fn stop(state: &Path, force: bool) -> Result<Value> {
    let owner = wire::rpc(state, "status", json!({}), true, 5.)?;
    let generation = &owner["generation"];
    if !force {
        wire::rpc(
            state,
            "prepare_stop",
            json!({"generation":generation}),
            false,
            5.,
        )?;
    }
    // Pin both shutdown calls to the live owner's generation, even if discovery changes.
    wire::rpc(state, "stop", json!({"generation":generation}), true, 5.)?;
    let deadline = Instant::now() + Duration::from_secs(15);
    while Instant::now() < deadline {
        let lock = lock_file(state, false)?;
        if try_lock(&lock)? {
            return Ok(
                json!({"stopped":true,"generation":generation,"discarded":force,"state_dir":state}),
            );
        }
        sleep(Duration::from_millis(100));
    }
    bail!("Shutdown is still in progress; inspect the supervisor log.")
}

// Declared after the flock guard so cleanup runs before the lock is released.
struct Owned<'a> {
    state: &'a Path,
    children: Vec<Child>,
}
impl Drop for Owned<'_> {
    fn drop(&mut self) {
        for child in self.children.iter_mut().rev() {
            while let Err(error) = terminate(child) {
                // Keep ownership and endpoints until shutdown can be confirmed.
                eprintln!("Child shutdown: {error:#}");
                sleep(Duration::from_secs(1));
            }
        }
        if let Err(error) = retire_artifacts(self.state) {
            eprintln!("Retire artifacts: {error:#}");
        }
        for name in ENDPOINTS {
            if let Err(error) = unlink(&self.state.join("runtime").join(name)) {
                eprintln!("Remove endpoint: {error:#}");
            }
        }
    }
}

pub fn serve(state: &Path, license: &Path, resources: &Resources) -> Result<()> {
    unsafe {
        libc::umask(0o077);
        // Adopt orphaned group members so shutdown can reap them before ESRCH.
        ensure!(
            libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0,
            "Set supervisor child subreaper: {}",
            std::io::Error::last_os_error()
        );
    }
    let config = resources.config()?;
    let lock = lock_file(state, false)?;
    ensure!(try_lock(&lock)?, "Another supervisor owns this session.");
    let mut owned = Owned {
        state,
        children: Vec::new(),
    };
    let generation = uuid::Uuid::new_v4().simple().to_string()[..12].to_string();
    let runtime = state.join("runtime");
    for name in ENDPOINTS {
        unlink(&runtime.join(name))?;
    }
    let metadata = json!({"generation":generation,"protocol":wire::PROTOCOL,"display":"headless","state_dir":state});
    atomic_json(&runtime.join("instance.json"), &metadata)?;
    ensure!(
        fs::read_dir(state.join("bn/plugins"))?.next().is_none(),
        "Managed plugin directory must be empty: {}",
        state.join("bn/plugins").display()
    );
    let link = state.join("bn/license.dat");
    ensure!(
        !link.exists() || link.is_symlink(),
        "Refusing to replace a license file: {}",
        link.display()
    );
    unlink(&link)?;
    symlink(license, link)?;
    let source = resources
        .dir
        .parent()
        .context("Plugin parent")?
        .to_string_lossy();
    fs::write(
        state.join("bn/startup.py"),
        format!(
            "import sys\nsys.path.insert(0, {})\nfrom binja.bridge import start\nstart()\n",
            serde_json::to_string(&source)?
        ),
    )?;
    let mut settings = json!({"ui.allowWelcome":false,"ui.mcp.enabled":false});
    for name in [
        "Updates",
        "UpdateChannelList",
        "ReleaseNotes",
        "ExtensionManager",
        "ExternalResources",
        "Debuginfod",
        "WARP",
        "CollaborationServer",
    ] {
        settings[format!("network.enable{name}")] = json!(false);
    }
    atomic_json(&state.join("bn/settings.json"), &settings)?;
    retire_artifacts(state)?;
    let stopping = Arc::new(AtomicBool::new(false));
    for sig in [libc::SIGTERM, libc::SIGINT] {
        signal_hook::flag::register(sig, Arc::clone(&stopping))?;
    }
    let listener = wire::socket()?;
    listener.bind(&SockAddr::unix(runtime.join("control.sock"))?)?;
    listener.listen(8)?;
    let spawn = |program: &str, args: &[&str], log_name: &str, wayland: bool| -> Result<Child> {
        let mut command = Command::new(program);
        command.args(args);
        for key in [
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "DBUS_SESSION_BUS_ADDRESS",
            "PYTHONPATH",
            "PYTHONHOME",
            "LD_LIBRARY_PATH",
            "LD_PRELOAD",
            "BN_DISABLE_USER_SETTINGS",
        ] {
            command.env_remove(key);
        }
        for (key, path) in [
            ("XDG_RUNTIME_DIR", "runtime"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_DATA_HOME", "data"),
            ("TMPDIR", "tmp"),
            ("BN_USER_DIRECTORY", "bn"),
        ] {
            command.env(key, state.join(path));
        }
        for (key, value) in [
            ("BN_QSETTINGS_POSTFIX", "binja"),
            ("BN_DISABLE_CRASH_REPORTING", "1"),
            ("BN_DISABLE_USER_PLUGINS", "1"),
            ("PYTHONNOUSERSITE", "1"),
            ("WLR_BACKENDS", "headless"),
            ("WLR_HEADLESS_OUTPUTS", "1"),
            ("WLR_RENDERER", "pixman"),
            ("QT_QPA_PLATFORM", "wayland"),
        ] {
            command.env(key, value);
        }
        command
            .env("BINJA_STATE_DIR", state)
            .env("BINJA_GENERATION", &generation);
        if wayland {
            command.env("WAYLAND_DISPLAY", "wayland-0");
        }
        let log = File::create(state.join("logs").join(log_name))?;
        command.stdout(log.try_clone()?).stderr(log);
        detached(&mut command);
        // Spawn on the long-lived supervisor main thread: PDEATHSIG is tied to
        // the spawning thread, not merely its process. Check the fork/prctl race.
        let parent = unsafe { libc::getpid() };
        unsafe {
            command.pre_exec(move || {
                if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) < 0 {
                    return Err(std::io::Error::last_os_error());
                }
                if libc::getppid() != parent {
                    libc::_exit(1);
                }
                Ok(())
            });
        }
        Ok(command
            .spawn()
            .with_context(|| format!("Start {program}"))?)
    };
    owned.children.push(spawn(
        config["labwc"].as_str().context("labwc path")?,
        &["-C", "/dev/null"],
        "labwc.log",
        false,
    )?);
    let deadline = Instant::now() + Duration::from_secs(15);
    while !runtime.join("wayland-0").exists() {
        ensure!(
            owned.children[0].try_wait()?.is_none()
                && Instant::now() < deadline
                && !stopping.load(Ordering::Relaxed),
            "Private compositor did not start; inspect labwc.log."
        );
        sleep(Duration::from_millis(100));
    }
    owned.children.push(spawn(
        config["runtime"].as_str().context("runtime path")?,
        &["-n"],
        "binaryninja.log",
        true,
    )?);
    let deadline = Instant::now() + Duration::from_secs(60);
    let mut ready = false;
    while !stopping.load(Ordering::Relaxed) {
        for child in &mut owned.children {
            if child.try_wait()?.is_some() {
                return Ok(());
            }
        }
        if !ready {
            ready = wire::rpc(state, "hello", json!({"generation":generation}), false, 0.2).is_ok();
            ensure!(
                ready || Instant::now() < deadline,
                "GUI receiver did not become ready; inspect binaryninja.log."
            );
        }
        let mut poll = libc::pollfd {
            fd: listener.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        let count = unsafe { libc::poll(&mut poll, 1, 200) };
        if count < 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error.into());
        }
        if count == 0 {
            continue;
        }
        let (connection, _) = listener.accept()?;
        connection.set_write_timeout(Some(Duration::from_secs(2)))?;
        let response = (|| -> Result<Value> {
            let request = wire::receive(&connection, wire::MAX_REQUEST, Duration::from_secs(2))?;
            ensure!(
                request["generation"] == generation && request["protocol"] == wire::PROTOCOL,
                "Session generation or protocol mismatch."
            );
            match request["op"].as_str() {
                Some("stop") => stopping.store(true, Ordering::Relaxed),
                Some("status") => (),
                _ => bail!("Unknown supervisor operation."),
            }
            let mut value = metadata.clone();
            value["ready"] = json!(ready);
            Ok(value)
        })();
        let reply = match response {
            Ok(data) => json!({"protocol":wire::PROTOCOL,"generation":generation,"data":data}),
            Err(error) => {
                json!({"protocol":wire::PROTOCOL,"generation":generation,"error":format!("{error:#}")})
            }
        };
        let _ = wire::send(&connection, &reply, wire::MAX_RESPONSE);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shutdown_reaps_resistant_group_after_leader_already_exited() {
        assert_eq!(
            unsafe { libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) },
            0
        );
        let ready = std::env::temp_dir().join(format!("binja-group-{}", uuid::Uuid::new_v4()));
        let mut command = Command::new("bash");
        command.args(["-c",
            "(trap '' TERM; touch \"$1\"; while :; do sleep 1; done) & while [ ! -f \"$1\" ]; do sleep .01; done",
            "group-test"]).arg(&ready).stdout(Stdio::null()).stderr(Stdio::null());
        detached(&mut command);
        let mut child = command.spawn().unwrap();
        let group = child.id() as i32;
        // Bash exits while its resistant background child retains the group.
        child.wait().unwrap();
        assert!(signal_group(group, 0).unwrap());
        terminate(&mut child).unwrap();
        assert!(!signal_group(group, 0).unwrap());
        fs::remove_file(ready).unwrap();
    }
}
