//! The loopback half of the Spotify OAuth flow.
//!
//! Spotify redirects to `http://127.0.0.1:8888/callback?code=…&state=…` after the
//! user authorizes, so something local has to be listening. That used to be
//! Python's `http.server` inside `wizard/oauth_step.py`, reached by spawning
//! `uv run spotify-mcp reauth`.
//!
//! Only the listening happens here. Building the authorize URL, checking `state`,
//! exchanging the code and encrypting the tokens are in TS
//! (`packages/shared-ts/pkce.ts` + `fernet.ts`), shared with the Worker so the
//! cron decrypts with exactly the code the app encrypted with.
//!
//! A raw `TcpListener` rather than an HTTP crate: this needs to read one request
//! line and write one fixed response, and the first line of an HTTP/1.1 request
//! is `GET <path> HTTP/1.1`. An HTTP server dependency would be more code to
//! audit than the thing it replaces.

use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::time::{Duration, Instant};

/// How long to wait for the user to finish authorizing in the browser.
/// Generous: it can include creating a Spotify account and a 2FA prompt.
const TIMEOUT: Duration = Duration::from_secs(300);

/// How often to check for a connection while waiting. Long enough to be idle,
/// short enough that finishing the flow feels immediate.
const POLL: Duration = Duration::from_millis(100);

const PAGE: &str = "<!doctype html><html><head><meta charset=\"utf-8\">\
<title>Spotify authorized</title></head>\
<body style=\"font-family:system-ui;padding:3rem;text-align:center\">\
<h1>Authorized</h1><p>You can close this tab and go back to the app.</p>\
</body></html>";

fn respond(mut stream: impl Write) {
    // Deliberately a fixed page: echoing any part of the query back into HTML
    // would be reflected XSS, in the user's own browser, for no benefit.
    let _ = write!(
        stream,
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\
         Content-Length: {}\r\nConnection: close\r\n\r\n{}",
        PAGE.len(),
        PAGE
    );
}

/// Pull the query string out of an HTTP request line (`GET /callback?x=1 HTTP/1.1`).
/// `None` when the path is not the callback — browsers also ask for /favicon.ico.
fn callback_query(request_line: &str) -> Option<String> {
    let path = request_line.split_whitespace().nth(1)?;
    let (path, query) = path.split_once('?')?;
    if path != "/callback" {
        return None;
    }
    Some(query.to_string())
}

/// Bind the callback port, open the browser, and return the callback's raw query
/// string. The caller checks `state` and exchanges the code.
///
/// Binding happens *before* the browser opens: the other order is a race where a
/// fast redirect arrives at a closed port and the user sees a connection error
/// with no way to retry except starting over.
pub fn await_callback(authorize_url: &str, port: u16) -> Result<String, String> {
    let listener = TcpListener::bind(("127.0.0.1", port)).map_err(|e| {
        format!(
            "could not listen on 127.0.0.1:{port} ({e}). Another copy of this app, \
             or another program using port {port}, will block the Spotify redirect."
        )
    })?;
    listener
        .set_nonblocking(true)
        .map_err(|e| format!("could not configure the callback listener: {e}"))?;

    tauri_plugin_opener::open_url(authorize_url, None::<&str>)
        .map_err(|e| format!("could not open your browser: {e}"))?;

    let deadline = Instant::now() + TIMEOUT;
    while Instant::now() < deadline {
        match listener.accept() {
            Ok((stream, _)) => {
                // Blocking again for the read: the connection is here, and a
                // partial first line is not a case worth polling for.
                let _ = stream.set_nonblocking(false);
                let mut line = String::new();
                if BufReader::new(&stream).read_line(&mut line).is_err() {
                    continue;
                }
                match callback_query(&line) {
                    Some(query) => {
                        respond(&stream);
                        return Ok(query);
                    }
                    // Not the callback (favicon, a stray probe): answer it so the
                    // browser is not left hanging, then keep waiting.
                    None => respond(&stream),
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(POLL),
            Err(e) => return Err(format!("callback listener failed: {e}")),
        }
    }
    Err(format!(
        "timed out after {}s waiting for Spotify to redirect back. \
         If you finished authorizing, try again.",
        TIMEOUT.as_secs()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_the_query_from_a_callback_request() {
        assert_eq!(
            callback_query("GET /callback?code=abc&state=xyz HTTP/1.1"),
            Some("code=abc&state=xyz".to_string())
        );
    }

    #[test]
    fn ignores_requests_that_are_not_the_callback() {
        // Browsers ask for this unprompted; treating it as the callback would
        // end the flow with an empty query before the real redirect arrives.
        assert_eq!(callback_query("GET /favicon.ico?x=1 HTTP/1.1"), None);
        assert_eq!(callback_query("GET /callback HTTP/1.1"), None);
        assert_eq!(callback_query("garbage"), None);
        assert_eq!(callback_query(""), None);
    }

    #[test]
    fn passes_an_error_callback_through_for_the_caller_to_report() {
        // Spotify redirects here with ?error=access_denied when the user clicks
        // "Cancel". That is not this layer's problem to interpret.
        assert_eq!(
            callback_query("GET /callback?error=access_denied&state=xyz HTTP/1.1"),
            Some("error=access_denied&state=xyz".to_string())
        );
    }

    #[test]
    fn writes_a_fixed_page_that_does_not_echo_the_query() {
        let mut out: Vec<u8> = Vec::new();
        respond(&mut out);
        let text = String::from_utf8(out).unwrap();
        assert!(text.starts_with("HTTP/1.1 200 OK"));
        assert!(text.contains("Content-Length: "));
        assert!(text.ends_with(PAGE));
    }
}
