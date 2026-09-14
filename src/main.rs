mod api;
mod render;
mod resources;
mod session;
mod wire;

use anyhow::{Context, Result, ensure};
use clap::{Args, Parser, Subcommand};
use resources::{Resources, absolute, state_path};
use serde_json::{Value, json};
use std::{
    fs,
    io::{self, IsTerminal, Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Parser)]
#[command(
    name = "binja",
    about = "Binary Ninja for agents. Start with `binja skill` for the workflow guide."
)]
struct Cli {
    #[arg(
        long,
        global = true,
        default_value = ".binja",
        help = "Session directory (default: .binja in the working directory)"
    )]
    state_dir: PathBuf,
    #[arg(
        long,
        global = true,
        help = "Machine-readable full record; submitting/accepted events on stderr"
    )]
    json: bool,
    #[arg(
        long,
        global = true,
        help = "Include the full record, including metadata and inline previews"
    )]
    verbose: bool,
    #[arg(
        long,
        global = true,
        help = "View handle, unique filename/path, or active"
    )]
    target: Option<String>,
    #[command(subcommand)]
    command: Commands,
}
#[derive(Args)]
struct Execution {
    #[arg(long, help = "Deliberately skip the analysis readiness gate")]
    allow_incomplete: bool,
    #[arg(
        long,
        help = "Submit and return immediately with the recoverable request ID"
    )]
    no_wait: bool,
    #[arg(long, default_value="30", value_parser=wait_seconds, help="Wait seconds after admission; timeout leaves work running")]
    wait: f64,
    #[arg(
        long,
        help = "Reuse an exact ID without replay. Construct GENERATION:rUNIQUE_ID: generation from status --json; UNIQUE_ID is 1-64 ASCII letters, digits, _ or -"
    )]
    request_id: Option<String>,
}
#[derive(Args)]
struct Page {
    #[arg(
        long,
        default_value = "0",
        help = "Skip rendered rows (function listings only)"
    )]
    offset: usize,
    #[arg(long, default_value = "64", value_parser = clap::value_parser!(u32).range(1..), help = "Maximum rendered rows per page")]
    limit: u32,
}
fn wait_seconds(value: &str) -> std::result::Result<f64, String> {
    let seconds: f64 = value.parse().map_err(|_| "wait must be a number")?;
    if seconds.is_finite() && (0.0..=9_000_000_000.0).contains(&seconds) {
        Ok(seconds)
    } else {
        Err("wait must be finite, nonnegative seconds within the server timeout range".into())
    }
}
#[derive(Subcommand)]
enum Commands {
    #[command(about = "Print the packaged workflow guide (no session required)")]
    Skill,
    #[command(about = "Look up API documentation and class members without a GUI")]
    Api {
        #[command(subcommand)]
        command: Api,
    },
    #[command(about = "Start or reuse a private Wayland session")]
    Start {
        #[arg(long)]
        license: Option<PathBuf>,
        #[arg(long, default_value="headless", value_parser=["headless"])]
        display: String,
    },
    #[command(about = "Show the session, file/view counts, and pending work")]
    Status,
    #[command(about = "List explicit view handles and paths")]
    Targets,
    #[command(about = "Stop the owned session")]
    Stop {
        #[arg(long, help = "Terminate and discard unsaved work")]
        force: bool,
    },
    #[command(about = "Execute Python against a retained target (file, -c, or stdin)")]
    Py {
        #[arg(long, conflicts_with = "code")]
        file: Option<PathBuf>,
        #[arg(short = 'c')]
        code: Option<String>,
        #[arg(
            long = "args",
            default_value = "{}",
            help = "JSON value exposed as args, separate from source"
        )]
        parameters: String,
        #[arg(long)]
        no_target: bool,
        #[command(flatten)]
        execution: Execution,
    },
    #[command(about = "Open a binary or BNDB and wait for analysis")]
    Open {
        path: PathBuf,
        #[command(flatten)]
        execution: Execution,
    },
    #[command(about = "Save the intended target to an explicit .bndb path")]
    Save {
        path: PathBuf,
        #[command(flatten)]
        execution: Execution,
    },
    #[command(about = "Read the GUI's rendered Pseudo C for a function")]
    Decompile {
        function: String,
        #[command(flatten)]
        page: Page,
        #[command(flatten)]
        execution: Execution,
    },
    #[command(about = "Read addressed IL; MLIL is the default fallback from decompilation")]
    Il {
        function: String,
        #[arg(long, default_value = "mlil", value_parser = ["hlil", "mlil", "llil"])]
        view: String,
        #[arg(long)]
        ssa: bool,
        #[command(flatten)]
        page: Page,
        #[command(flatten)]
        execution: Execution,
    },
    #[command(
        about = "Read function disassembly, or a linear --count/--end window without function analysis"
    )]
    Disasm {
        #[arg(value_name = "FUNCTION|ADDRESS")]
        identifier: String,
        #[arg(long, conflicts_with_all = ["end", "offset"], value_parser = clap::value_parser!(u64).range(1..), help = "Decode this many instructions starting at ADDRESS")]
        count: Option<u64>,
        #[arg(
            long,
            conflicts_with = "offset",
            help = "Exclusive end address for linear decoding"
        )]
        end: Option<String>,
        #[command(flatten)]
        page: Page,
        #[command(flatten)]
        execution: Execution,
    },
    #[command(about = "List pending and newest five finished requests, plus cap rejections")]
    Requests {
        #[arg(long, help = "Include full finished history")]
        all: bool,
    },
    #[command(about = "Retrieve an existing request; never re-execute it")]
    Request {
        id: String,
        #[arg(long, default_value="0",value_parser=wait_seconds)]
        wait: f64,
    },
    #[command(about = "Cancel queued work or a readiness wait; successful cancellation exits 0")]
    Cancel { id: String },
    #[command(name = "__supervisor", hide = true)]
    Supervisor { state: PathBuf, license: PathBuf },
}
#[derive(Subcommand)]
enum Api {
    Paths,
    Search {
        query: String,
        #[arg(long, default_value = "15")]
        limit: usize,
    },
    Show {
        symbol: String,
    },
    #[command(about = "List public static members, including indexed bases, without truncation")]
    Members {
        class: String,
        #[arg(
            long = "match",
            help = "Case-insensitive literal substring of the member name"
        )]
        name_match: Option<String>,
    },
}

fn submit(cli: &Cli, state: &Path, execution: &Execution, mut spec: Value) -> Result<Value> {
    let hello = wire::rpc(state, "hello", json!({}), false, 5.)?;
    let generation = hello["generation"].as_str().context("Session generation")?;
    let id = execution.request_id.clone().unwrap_or_else(|| {
        format!(
            "{generation}:r{}",
            &uuid::Uuid::new_v4().simple().to_string()[..16]
        )
    });
    if cli.json {
        eprintln!("{}", json!({"event":"submitting","id":id}));
    } else {
        eprintln!("Request {id}");
    }
    io::stderr().flush()?;
    spec["id"] = json!(id);
    spec["allow_incomplete"] = json!(execution.allow_incomplete);
    spec["target"] = match &cli.target {
        Some(t) if t.contains('/') => json!(absolute(t)?),
        Some(t) => json!(t),
        None => Value::Null,
    };
    let wait = if execution.no_wait {
        0.
    } else {
        execution.wait
    };
    let mut value = wire::call(
        state,
        "submit",
        json!({"spec":spec,"wait":wait}),
        false,
        Duration::from_secs_f64(wait + 5.),
        |v, existing| render::receipt(v, existing, cli.json, cli.verbose),
    )?;
    if !execution.no_wait && render::pending(&value) {
        value["client_wait_expired"] = json!(true);
    }
    Ok(value)
}

fn command_script(resources: &Resources, kind: &str, args: Value) -> Result<Value> {
    let filename = resources.dir.join("commands").join(format!("{kind}.py"));
    let source =
        fs::read_to_string(&filename).with_context(|| format!("Read {}", filename.display()))?;
    Ok(
        json!({"kind":kind,"filename":filename,"source":source,"args":args,"no_target":kind == "open"}),
    )
}

fn run(cli: &Cli) -> Result<i32> {
    let resources = Resources::locate()?;
    if let Commands::Supervisor { state, license } = &cli.command {
        session::serve(state, license, &resources)?;
        return Ok(0);
    }
    if matches!(cli.command, Commands::Skill) {
        print!("{}", fs::read_to_string(resources.dir.join("guide.md"))?);
        return Ok(0);
    }
    if let Commands::Api { command } = &cli.command {
        let (op, value, limit, name_match) = match command {
            Api::Paths => ("paths", "", 15, None),
            Api::Show { symbol } => ("show", symbol.as_str(), 15, None),
            Api::Search { query, limit } => ("search", query.as_str(), *limit, None),
            Api::Members { class, name_match } => {
                ("members", class.as_str(), 0, name_match.as_deref())
            }
        };
        let result = api::query(&resources, op, value, limit, name_match)?;
        render::render(
            &result,
            &format!("api {op}"),
            cli.json,
            cli.verbose,
            Path::new(""),
        )?;
        return Ok(0);
    }
    let state = state_path(&cli.state_dir)?;
    let (mut value, command, no_wait) = match &cli.command {
        Commands::Start { license, .. } => (
            session::start(&state, license.as_deref(), &resources)?,
            "start",
            false,
        ),
        Commands::Stop { force } => (session::stop(&state, *force)?, "stop", false),
        Commands::Status => (session::status(&state)?, "status", false),
        Commands::Targets => (
            wire::rpc(&state, "targets", json!({}), false, 5.)?,
            "targets",
            false,
        ),
        Commands::Requests { all } => (
            wire::rpc(&state, "requests", json!({"all":all}), false, 5.)?,
            if *all { "requests --all" } else { "requests" },
            false,
        ),
        Commands::Request { id, wait } => (
            wire::rpc(
                &state,
                "request",
                json!({"id":id,"wait":wait}),
                false,
                wait + 5.,
            )?,
            "request",
            false,
        ),
        Commands::Cancel { id } => (
            wire::rpc(&state, "cancel", json!({"id":id}), false, 5.)?,
            "cancel",
            false,
        ),
        Commands::Py {
            file,
            code,
            parameters,
            no_target,
            execution,
        } => {
            ensure!(
                !(*no_target && cli.target.is_some()),
                "--no-target and --target cannot be combined."
            );
            let (filename, source) = if let Some(file) = file {
                let path = absolute(file)?;
                (
                    path.to_string_lossy().into_owned(),
                    fs::read_to_string(&path)
                        .with_context(|| format!("Read {}", path.display()))?,
                )
            } else if let Some(code) = code {
                ("<binja -c>".into(), code.clone())
            } else {
                ensure!(
                    !io::stdin().is_terminal(),
                    "Supply py --file SCRIPT, py -c CODE, or Python on stdin."
                );
                let mut source = String::new();
                io::stdin().read_to_string(&mut source)?;
                ("<binja stdin>".into(), source)
            };
            let args: Value = serde_json::from_str(parameters).context("Parse --args JSON")?;
            (
                submit(
                    cli,
                    &state,
                    execution,
                    json!({"kind":"py","filename":filename,"source":source,"args":args,"no_target":no_target}),
                )?,
                "py",
                execution.no_wait,
            )
        }
        Commands::Open { path, execution } | Commands::Save { path, execution } => {
            let open = matches!(cli.command, Commands::Open { .. });
            ensure!(
                !(open && cli.target.is_some()),
                "open selects a file by path; omit --target."
            );
            let path = absolute(path)?;
            if open {
                ensure!(
                    path.is_file(),
                    "Input file does not exist: {}",
                    path.display()
                );
            }
            let kind = if open { "open" } else { "save" };
            (
                submit(
                    cli,
                    &state,
                    execution,
                    command_script(&resources, kind, json!({"path":path}))?,
                )?,
                kind,
                execution.no_wait,
            )
        }
        Commands::Decompile {
            function,
            page,
            execution,
        }
        | Commands::Il {
            function,
            page,
            execution,
            ..
        }
        | Commands::Disasm {
            identifier: function,
            page,
            execution,
            ..
        } => {
            let mut args = json!({"function":function,"offset":page.offset,"limit":page.limit});
            let kind = match &cli.command {
                Commands::Decompile { .. } => "decompile",
                Commands::Il { view, ssa, .. } => {
                    args["view"] = json!(view);
                    args["ssa"] = json!(ssa);
                    "il"
                }
                Commands::Disasm { count, end, .. } => {
                    args["count"] = json!(count);
                    args["end"] = json!(end);
                    "disasm"
                }
                _ => unreachable!(),
            };
            let spec = command_script(&resources, kind, args)?;
            (
                submit(cli, &state, execution, spec)?,
                kind,
                execution.no_wait,
            )
        }
        _ => unreachable!(),
    };
    if value["client_wait_expired"] == true {
        value["recovery_command"] = json!(render::recovery(&state, render::text(&value, "id")));
    }
    render::render(&value, command, cli.json, cli.verbose, &state)?;
    if command == "cancel" {
        return Ok(0);
    }
    if matches!(render::text(&value, "status"), "failed" | "cancelled") {
        return Ok(1);
    }
    if render::pending(&value) && !no_wait {
        return Ok(2);
    }
    Ok(0)
}
fn main() {
    let cli = Cli::parse();
    if !matches!(cli.command, Commands::Supervisor { .. }) {
        // Rust ignores SIGPIPE, so `binja skill | head -1` would panic on EPIPE.
        // The supervisor keeps the ignore: its lifetime must not depend on a reader.
        unsafe { libc::signal(libc::SIGPIPE, libc::SIG_DFL) };
    }
    let code = match run(&cli) {
        Ok(code) => code,
        Err(error) => {
            if cli.json {
                println!("{}", json!({"error":format!("{error:#}")}));
            } else {
                eprintln!("binja: {error:#}");
            }
            1
        }
    };
    std::process::exit(code);
}
