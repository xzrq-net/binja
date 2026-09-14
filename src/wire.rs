use anyhow::{Context, Result, bail, ensure};
use serde_json::{Value, json};
use socket2::{Domain, SockAddr, Socket, Type};
use std::{
    fs,
    os::fd::AsRawFd,
    path::Path,
    time::{Duration, Instant},
};

pub const PROTOCOL: u64 = 3;
pub const CHUNK: usize = 32 * 1024;
pub const MAX_REQUEST: usize = 4 * 1024 * 1024;
pub const MAX_RESPONSE: usize = 64 * 1024 * 1024;

pub fn socket() -> Result<Socket> {
    Ok(Socket::new(Domain::UNIX, Type::SEQPACKET, None)?)
}

pub fn send(socket: &Socket, value: &Value, limit: usize) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    ensure!(bytes.len() <= limit, "RPC message exceeds {limit} bytes.");
    for chunk in bytes.chunks(CHUNK) {
        let mut packet = Vec::with_capacity(chunk.len() + 1);
        packet.push(1);
        packet.extend_from_slice(chunk);
        ensure!(
            socket.send(&packet)? == packet.len(),
            "Incomplete RPC packet send."
        );
    }
    ensure!(socket.send(&[0])? == 1, "Incomplete RPC end packet send.");
    Ok(())
}

pub fn receive(socket: &Socket, limit: usize, timeout: Duration) -> Result<Value> {
    let deadline = Instant::now() + timeout;
    let mut bytes = Vec::new();
    let mut packet = vec![0u8; CHUNK + 1];
    loop {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .context("RPC read timed out; inspect the existing request ID.")?;
        socket.set_read_timeout(Some(remaining))?;
        // MSG_TRUNC reports the original packet length, even if the buffer is smaller.
        let n = unsafe {
            libc::recv(
                socket.as_raw_fd(),
                packet.as_mut_ptr().cast(),
                packet.len(),
                libc::MSG_TRUNC,
            )
        };
        if n < 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error)
                .context("Read RPC packet; inspect the existing request ID after a disconnect");
        }
        let n = n as usize;
        ensure!(
            n > 0,
            "Incomplete RPC message: disconnected before end packet."
        );
        ensure!(n <= packet.len(), "Oversized RPC packet.");
        if n == 1 && packet[0] == 0 {
            break;
        }
        ensure!(n > 1 && packet[0] == 1, "Invalid RPC data packet.");
        ensure!(
            bytes.len() + n - 1 <= limit,
            "RPC message exceeds {limit} bytes."
        );
        bytes.extend_from_slice(&packet[1..n]);
    }
    let value: Value = serde_json::from_slice(&bytes)?;
    ensure!(value.is_object(), "RPC message must be a JSON object.");
    Ok(value)
}

pub fn generation(state: &Path) -> Result<String> {
    let metadata: Value = serde_json::from_slice(
        &fs::read(state.join("runtime/instance.json")).with_context(|| {
            format!(
                "No session metadata in {}; run binja start.",
                state.display()
            )
        })?,
    )?;
    Ok(metadata["generation"]
        .as_str()
        .context("Missing session generation")?
        .into())
}

pub fn call(
    state: &Path,
    op: &str,
    mut params: Value,
    control: bool,
    timeout: Duration,
    mut accepted: impl FnMut(&Value, bool) -> Result<()>,
) -> Result<Value> {
    let generation = match params["generation"].as_str() {
        Some(generation) => generation.to_owned(),
        None => generation(state)?,
    };
    params["protocol"] = json!(PROTOCOL);
    params["generation"] = json!(generation);
    params["op"] = json!(op);
    let endpoint = state.join(if control {
        "runtime/control.sock"
    } else {
        "runtime/rpc.sock"
    });
    let socket = socket()?;
    socket.set_write_timeout(Some(Duration::from_secs(5)))?;
    socket
        .connect(&SockAddr::unix(&endpoint)?)
        .with_context(|| {
            format!(
                "Session endpoint unavailable; inspect {}/logs",
                state.display()
            )
        })?;
    send(&socket, &params, MAX_REQUEST)?;
    loop {
        let response = receive(&socket, MAX_RESPONSE, timeout)?;
        ensure!(
            response["protocol"] == PROTOCOL && response["generation"] == generation,
            "Session identity or protocol mismatch; restart with the matching package."
        );
        if let Some(error) = response.get("error") {
            bail!("{}", error.as_str().unwrap_or("RPC error"));
        }
        let data = response.get("data").context("RPC reply has no data")?;
        if response["event"] == "accepted" {
            accepted(data, response["existing"] == true)?;
        }
        if control || response["final"] == true {
            return Ok(data.clone());
        }
        ensure!(
            response["event"] == "accepted",
            "Unexpected nonfinal RPC reply."
        );
    }
}

pub fn rpc(state: &Path, op: &str, params: Value, control: bool, timeout: f64) -> Result<Value> {
    call(
        state,
        op,
        params,
        control,
        Duration::from_secs_f64(timeout),
        |_, _| Ok(()),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn chunked_messages_preserve_unicode_and_large_integers() {
        let (a, b) = Socket::pair(Domain::UNIX, Type::SEQPACKET, None).unwrap();
        let value: Value = serde_json::from_str(&format!(
            r#"{{"source":"{}","address":1267650600228229401496703205376}}"#,
            "λ".repeat(100000)
        ))
        .unwrap();
        let expected = value.clone();
        let writer = std::thread::spawn(move || {
            send(&a, &value, MAX_REQUEST).unwrap();
            send(&a, &json!({"done":true}), MAX_REQUEST).unwrap();
        });
        assert_eq!(
            receive(&b, MAX_RESPONSE, Duration::from_secs(2)).unwrap(),
            expected
        );
        assert_eq!(
            receive(&b, MAX_RESPONSE, Duration::from_secs(2)).unwrap(),
            json!({"done":true})
        );
        writer.join().unwrap();
    }
    #[test]
    fn reject_truncation_missing_end_and_oversized_messages() {
        for packet in [vec![1; CHUNK + 2], vec![2, 3], vec![1]] {
            let (a, b) = Socket::pair(Domain::UNIX, Type::SEQPACKET, None).unwrap();
            a.send(&packet).unwrap();
            assert!(receive(&b, MAX_REQUEST, Duration::from_secs(1)).is_err());
        }
        let (a, b) = Socket::pair(Domain::UNIX, Type::SEQPACKET, None).unwrap();
        a.send(b"\x01{}").unwrap();
        drop(a);
        assert!(
            receive(&b, MAX_REQUEST, Duration::from_secs(1))
                .unwrap_err()
                .to_string()
                .contains("Incomplete")
        );
        let (a, b) = Socket::pair(Domain::UNIX, Type::SEQPACKET, None).unwrap();
        assert!(send(&a, &json!({"x":"long"}), 2).is_err());
        a.send(b"\x01{\"x\":42}").unwrap();
        assert!(receive(&b, 2, Duration::from_secs(1)).is_err());
    }
}
