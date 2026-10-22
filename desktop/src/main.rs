//! DS Decomp Studio in its own window.
//!
//! Starts the Python backend (`studio.py serve --no-browser`, no console, output in data/server.log) and shows the
//! existing web/ UI in a WebView2 window. If a studio already listens on the port, the window attaches to it and
//! leaves it running on close. The backend runs in a Windows job object: closing the window (or a crash of this
//! program) stops it with its machine tasks, like closing the old console did.
#![windows_subsystem = "windows"]

use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use tao::dpi::LogicalSize;
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder};
use tao::platform::windows::WindowExtWindows;
use tao::window::{Icon, WindowBuilder};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::UI::Shell::ShellExecuteW;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    MessageBoxW, IDYES, MB_ICONERROR, MB_ICONWARNING, MB_OK, MB_YESNO, SW_SHOWNORMAL,
};
use wry::{NewWindowResponse, WebContext, WebViewBuilder};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const TITLE: &str = "DS Decomp Studio";

enum Ui {
    Ready,
    Failed(String),
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}

fn message(hwnd: isize, text: &str, flags: u32) -> i32 {
    unsafe { MessageBoxW(hwnd as _, wide(text).as_ptr(), wide(TITLE).as_ptr(), flags) }
}

/// The studio folder: the first parent of the program that holds studio.py and web/ (desktop/target/release/ or
/// the studio folder itself when the .exe is copied there).
fn studio_dir() -> PathBuf {
    let exe = std::env::current_exe().unwrap_or_default();
    exe.ancestors()
        .find(|d| d.join("studio.py").is_file() && d.join("web").is_dir())
        .map(Path::to_path_buf)
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default())
}

/// Same interpreter as Studio.cmd: the workspace venv, else python from PATH.
fn python(studio: &Path) -> PathBuf {
    let venv = studio.join("..").join(".venv").join("Scripts").join("python.exe");
    if venv.is_file() { venv } else { PathBuf::from("python") }
}

fn port() -> u16 {
    std::env::var("DSSTUDIO_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8765)
}

fn listening(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn http_get(port: u16, path: &str) -> Option<String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_millis(500)).ok()?;
    s.set_read_timeout(Some(Duration::from_secs(3))).ok()?;
    write!(s, "GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").ok()?;
    let mut out = String::new();
    s.read_to_string(&mut out).ok()?;
    out.split_once("\r\n\r\n").map(|(_, body)| body.to_string())
}

/// Machine tasks that closing the window would stop (server.py answers json.dumps with ": " separators).
fn active_jobs(port: u16) -> usize {
    http_get(port, "/api/jobs")
        .map(|b| b.matches("\"state\": \"running\"").count() + b.matches("\"state\": \"queued\"").count())
        .unwrap_or(0)
}

/// A job object that kills the backend and everything it started when this program ends, whatever the way.
fn kill_with_us(child: &Child) {
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info as *const _ as *const _,
                                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32);
        AssignProcessToJobObject(job, child.as_raw_handle() as _);
        // the handle stays open until the process ends: that is what keeps the backend alive
    }
}

fn start_backend(studio: &Path) -> std::io::Result<Child> {
    let log_path = studio.join("data").join("server.log");
    let _ = std::fs::create_dir_all(studio.join("data"));
    let mut log = OpenOptions::new().create(true).append(true).open(&log_path)?;
    let _ = writeln!(log, "\n--- {} : demarrage par DSDecompStudio.exe ---", TITLE);
    let err = log.try_clone()?;
    Command::new(python(studio))
        .args(["-u", "studio.py", "serve", "--no-browser"])
        .current_dir(studio)
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::null())
        .stdout(log)
        .stderr(err)
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
}

fn tail(path: &Path, n: usize) -> String {
    let t = std::fs::read_to_string(path).unwrap_or_default();
    let lines: Vec<&str> = t.lines().collect();
    lines[lines.len().saturating_sub(n)..].join("\n")
}

fn open_external(url: &str) {
    unsafe {
        ShellExecuteW(std::ptr::null_mut(), wide("open").as_ptr(), wide(url).as_ptr(), std::ptr::null(),
                      std::ptr::null(), SW_SHOWNORMAL);
    }
}

fn icon() -> Option<Icon> {
    // 32x32: the studio's green on its dark blue, a rounded square
    let n = 32u32;
    let mut px = Vec::with_capacity((n * n * 4) as usize);
    for y in 0..n {
        for x in 0..n {
            let (dx, dy) = ((x as i32 - 15).abs().max(12) - 12, (y as i32 - 15).abs().max(12) - 12);
            let inside = dx * dx + dy * dy <= 16;
            let ring = inside && (x < 4 || y < 4 || x > 27 || y > 27);
            let tri = x >= 11 && x <= 22 && (y as i32 - 15).abs() <= (x as i32 - 11) / 2 + 1 && x <= 22;
            let c: [u8; 4] = if !inside { [0, 0, 0, 0] } else if tri || ring { [0x6e, 0xe7, 0xb7, 255] } else { [0x17, 0x1b, 0x30, 255] };
            px.extend_from_slice(&c);
        }
    }
    Icon::from_rgba(px, n, n).ok()
}

const LOADING: &str = r#"<!doctype html><html><body style="margin:0;background:#0e1120;color:#e7eaff;
font:15px 'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<div style="text-align:center"><div style="font:700 18px Consolas,monospace;letter-spacing:2px;color:#6ee7b7">
&#9654; DS DECOMP STUDIO</div><p style="color:#8f98c9">Demarrage du serveur...</p></div></body></html>"#;

fn main() {
    let studio = studio_dir();
    let port = port();
    let base = format!("http://127.0.0.1:{port}");

    // An already running studio (Studio.cmd, another window): use it and leave it alone on close
    let mut backend: Option<Child> = None;
    if !listening(port) {
        match start_backend(&studio) {
            Ok(c) => {
                kill_with_us(&c);
                backend = Some(c);
            }
            Err(e) => {
                message(0, &format!("Impossible de lancer Python ({}) :\n{e}", python(&studio).display()), MB_ICONERROR);
                return;
            }
        }
    }

    let event_loop = EventLoopBuilder::<Ui>::with_user_event().build();
    let window = WindowBuilder::new()
        .with_title(TITLE)
        .with_window_icon(icon())
        .with_inner_size(LogicalSize::new(1440.0, 920.0))
        .with_min_inner_size(LogicalSize::new(720.0, 480.0))
        .build(&event_loop)
        .expect("window");

    let mut ctx = WebContext::new(Some(studio.join("data").join("webview2")));
    let local = base.clone();
    let webview = WebViewBuilder::new_with_web_context(&mut ctx)
        .with_html(LOADING)
        .with_devtools(true)
        // links to GitHub, ByteMatch...: in the usual browser, the window stays on the studio
        .with_navigation_handler(move |url| {
            if url.starts_with(&local) || !url.starts_with("http") {
                return true;
            }
            open_external(&url);
            false
        })
        .with_new_window_req_handler(|url, _features| {
            open_external(&url);
            NewWindowResponse::Deny
        })
        .build(&window);
    let webview = match webview {
        Ok(w) => w,
        Err(e) => {
            message(0, &format!("WebView2 indisponible : {e}\nInstallez le runtime Microsoft Edge WebView2."), MB_ICONERROR);
            return;
        }
    };

    // Wait for the server in the background, then show the UI
    let proxy = event_loop.create_proxy();
    let started_here = backend.is_some();
    let log_path = studio.join("data").join("server.log");
    let mut pid = backend.as_ref().map(|c| c.id());
    std::thread::spawn(move || {
        let t0 = Instant::now();
        loop {
            if listening(port) {
                let _ = proxy.send_event(Ui::Ready);
                return;
            }
            if t0.elapsed() > Duration::from_secs(90) {
                let _ = proxy.send_event(Ui::Failed(tail(&log_path, 25)));
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    });

    event_loop.run(move |event, _, flow| {
        *flow = ControlFlow::Wait;
        // the backend stopped by itself (error at start): say why instead of waiting
        if let (Some(c), Some(_)) = (backend.as_mut(), pid) {
            if let Ok(Some(st)) = c.try_wait() {
                pid = None;
                let why = tail(&studio.join("data").join("server.log"), 25);
                message(window.hwnd() as isize, &format!("Le serveur du studio s'est arrete ({st}).\n\n{why}"), MB_ICONERROR | MB_OK);
            }
        }
        match event {
            Event::UserEvent(Ui::Ready) => {
                let _ = webview.load_url(&base);
            }
            Event::UserEvent(Ui::Failed(log)) => {
                message(window.hwnd() as isize, &format!("Le serveur ne repond pas sur le port {port}.\n\n{log}"), MB_ICONERROR | MB_OK);
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                if started_here {
                    let n = active_jobs(port);
                    if n > 0 && message(window.hwnd() as isize,
                        &format!("{n} tache(s) machine en cours ou en attente.\nFermer le studio les arrete. Fermer quand meme ?"),
                        MB_ICONWARNING | MB_YESNO) != IDYES {
                        return;
                    }
                }
                pid = None; // stopped on purpose: no "the server stopped" message
                if let Some(c) = backend.as_mut() {
                    let _ = c.kill();
                    let _ = c.wait();
                }
                *flow = ControlFlow::Exit;
            }
            _ => {}
        }
    });
}
