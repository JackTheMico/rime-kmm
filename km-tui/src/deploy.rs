use std::path::{Path, PathBuf};
use std::process::Command;

use crate::config::Backend;

/// 需要跟随主词库一起同步到 Rime 数据目录的配套文件。
const COMPANIONS: &[&str] = &[
    "kongmingmas.schema.yaml",
    "kongmingmas_core.dict.yaml",
    "kongmingmas_ext.schema.yaml",
    "rime.lua",
];

/// 部署目标：Rime 的共享数据目录与用户数据目录。
///
/// `shared` 传给 librime 作为 shared_data_dir，`user` 作为 user_data_dir
/// （词库同步目标 + `build/*.table.bin` 产物目录）。
pub struct DeployTarget {
    pub shared: PathBuf,
    pub user: PathBuf,
    pub label: String,
}

/// 探测指定后端的实际部署目标。
pub fn detect(backend: Backend) -> Option<DeployTarget> {
    match backend {
        Backend::Xsime => detect_xsime(),
        Backend::Fcitx5Rime => Some(detect_fcitx5_rime()),
    }
}

/// 探测 XSIME 当前生效的资源目录与用户目录。
/// 优先读取 `~/.local/share/rimes/schemes/active.yaml` 指向的导入方案包。
fn detect_xsime() -> Option<DeployTarget> {
    let user_root = std::env::var("RIMES_USER_DIR")
        .ok()
        .filter(|p| p.starts_with('/'))
        .map(PathBuf::from)
        .or_else(|| dirs::data_dir().map(|d| d.join("rimes")))?;
    if !user_root.is_dir() {
        return None;
    }

    let text = std::fs::read_to_string(user_root.join("schemes/active.yaml")).unwrap_or_default();
    let (package, schema) = parse_active(&text);

    if let Some(id) = package {
        let resources = user_root.join("schemes/packages").join(&id);
        if resources.is_dir() {
            let learning = user_root.join("schemes/learning").join(&id);
            return Some(DeployTarget {
                label: format!("XSIME 方案包（schema: {}）", schema.as_deref().unwrap_or("未知")),
                shared: resources,
                user: learning,
            });
        }
    }

    // 未导入方案包时使用内置数据目录
    let data = user_root.join("data");
    data.is_dir().then(|| DeployTarget {
        label: format!("XSIME 内置数据（schema: {}）", schema.as_deref().unwrap_or("未知")),
        shared: data.clone(),
        user: data,
    })
}

/// 探测 fcitx5-rime 的用户 Rime 数据目录。
/// 优先 `RIME_USER_DIR`，其次 XDG 的 `fcitx5/rime`，再退回旧版 `~/.config/rime`。
fn detect_fcitx5_rime() -> DeployTarget {
    let xdg_user = dirs::data_dir()
        .map(|d| d.join("fcitx5/rime"))
        .unwrap_or_else(|| PathBuf::from("~/.local/share/fcitx5/rime"));
    let legacy = dirs::config_dir().map(|d| d.join("rime"));

    let user = std::env::var("RIME_USER_DIR")
        .ok()
        .filter(|p| p.starts_with('/'))
        .map(PathBuf::from)
        .filter(|p| p.is_dir())
        .or_else(|| xdg_user.clone().is_dir().then_some(xdg_user.clone()))
        .or_else(|| legacy.clone().filter(|p| p.is_dir()))
        .unwrap_or(xdg_user);

    let shared = PathBuf::from("/usr/share/rime-data");
    let shared = if shared.is_dir() { shared } else { user.clone() };

    DeployTarget {
        label: "fcitx5-rime 用户数据目录".into(),
        shared,
        user,
    }
}

/// 设置页展示用的探测摘要。
pub fn probe_desc(backend: Backend) -> String {
    match detect(backend) {
        Some(t) => format!("{} → {}", t.label, t.user.display()),
        None => "未检测到部署目录".into(),
    }
}

fn parse_active(text: &str) -> (Option<String>, Option<String>) {
    let mut package = None;
    let mut schema = None;
    for line in text.lines() {
        let line = line.trim();
        if let Some(v) = line.strip_prefix("package:") {
            let v = v.trim();
            if !v.is_empty() {
                package = Some(v.to_string());
            }
        } else if let Some(v) = line.strip_prefix("schema:") {
            let v = v.trim();
            if !v.is_empty() {
                schema = Some(v.to_string());
            }
        }
    }
    (package, schema)
}

/// 把词库及其配套文件同步到目标数据目录，然后编译并按后端重载。
/// `override_cmd` 为空时走内置编译（librime）；非空时只执行该命令。
pub fn sync_and_deploy(dict_path: &Path, override_cmd: Option<&str>, backend: Backend) -> String {
    let mut log = String::new();
    let Some(target) = detect(backend) else {
        log.push_str(&format!(
            "✖ 未检测到 {} 目录，请确认已安装对应输入法\n",
            backend.label()
        ));
        return log;
    };
    let Some(name) = dict_path.file_name() else {
        log.push_str("✖ 词库路径缺少文件名，无法同步\n");
        return log;
    };
    let repo_root = dict_path.parent().unwrap_or(Path::new("."));

    // 1. 同步主词库
    let dst_path = target.user.join(name);
    if dict_path.exists() {
        match std::fs::copy(dict_path, &dst_path) {
            Ok(bytes) => log.push_str(&format!(
                "✔ 同步词库：{} ({:.2} MB)\n",
                dst_path.display(),
                bytes as f64 / 1_048_576.0
            )),
            Err(e) => log.push_str(&format!("✖ 同步词库失败：{e}\n")),
        }
    } else {
        log.push_str(&format!("✖ 词库不存在：{}\n", dict_path.display()));
    }

    // 2. 同步配套文件（方案、核心/后缀词库、lua）
    for rel in COMPANIONS {
        let src = repo_root.join(rel);
        if !src.exists() {
            continue;
        }
        let dst = target.user.join(rel);
        if let Some(parent) = dst.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        match std::fs::copy(&src, &dst) {
            Ok(_) => log.push_str(&format!("✔ 同步 {rel}\n")),
            Err(e) => log.push_str(&format!("✖ 同步 {rel} 失败：{e}\n")),
        }
    }

    log.push_str(&format!(
        "⚙ 后端：{}\n⚙ 共享目录：{}\n⚙ 用户目录：{}\n",
        backend.label(),
        target.shared.display(),
        target.user.display()
    ));

    // 3. 编译 / 重载
    match override_cmd.map(str::trim).filter(|s| !s.is_empty()) {
        Some(cmd) => run_custom(cmd, &mut log),
        None => {
            run_builtin(&target, repo_root, &mut log);
            if let Some(reload) = backend.default_reload_cmd() {
                run_custom(reload, &mut log);
            }
        }
    }

    log
}

fn run_custom(cmd: &str, log: &mut String) {
    log.push_str(&format!("⚙ 重载命令：{cmd}\n"));
    match run_captured(cmd) {
        Ok(o) => {
            let out = String::from_utf8_lossy(&o.stdout);
            let err = String::from_utf8_lossy(&o.stderr);
            if o.status.success() {
                log.push_str("✔ 命令执行成功\n");
            } else {
                log.push_str(&format!(
                    "⚠ 命令返回异常码：{:?}\n{out}{err}\n",
                    o.status.code()
                ));
            }
        }
        Err(e) => log.push_str(&format!("✖ 执行失败：{e}\n")),
    }
}

/// 内置部署：用 `tools/km_deploy.c` 直接调用 librime 编译到用户目录。
fn run_builtin(target: &DeployTarget, repo_root: &Path, log: &mut String) {
    let bin = match ensure_deployer(repo_root) {
        Ok(b) => b,
        Err(e) => {
            log.push_str(&format!("✖ 准备部署器失败：{e}\n"));
            return;
        }
    };
    log.push_str(&format!("⚙ 编译：{} + librime\n", bin.display()));
    match Command::new(&bin)
        .arg(&target.shared)
        .arg(&target.user)
        .output()
    {
        Ok(o) if o.status.success() => log.push_str("✔ 部署完成\n"),
        Ok(o) => log.push_str(&format!(
            "✖ 部署失败（{:?}）：{}\n",
            o.status.code(),
            String::from_utf8_lossy(&o.stderr)
        )),
        Err(e) => log.push_str(&format!("✖ 无法运行部署器：{e}\n")),
    }
}

/// 按需编译 `tools/km_deploy.c`，缓存到 XDG cache 目录。
fn ensure_deployer(repo_root: &Path) -> Result<PathBuf, String> {
    let cache = dirs::cache_dir()
        .ok_or("找不到 cache 目录")?
        .join("km-tui");
    std::fs::create_dir_all(&cache).map_err(|e| e.to_string())?;
    let src = repo_root.join("tools/km_deploy.c");
    let bin = cache.join("km_deploy");
    let stale = match (bin.metadata(), src.metadata()) {
        (Ok(b), Ok(s)) => match (b.modified(), s.modified()) {
            (Ok(bt), Ok(st)) => bt < st,
            _ => false,
        },
        _ => true,
    };
    if stale {
        let out = Command::new("cc")
            .arg("-O2")
            .arg("-o")
            .arg(&bin)
            .arg(&src)
            .arg("-lrime")
            .output()
            .map_err(|e| format!("调用 cc 失败：{e}"))?;
        if !out.status.success() {
            return Err(String::from_utf8_lossy(&out.stderr).into_owned());
        }
    }
    Ok(bin)
}

fn run_captured(cmd: &str) -> std::io::Result<std::process::Output> {
    Command::new("sh").arg("-c").arg(cmd).output()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_active() {
        let text = "package: 75f1c5dc30f81cbd685ed329027693c3\nschema: kongmingmas\n";
        assert_eq!(parse_active(text).1.as_deref(), Some("kongmingmas"));
    }

    #[test]
    fn test_parse_active_empty() {
        assert_eq!(parse_active(""), (None, None));
    }

    #[test]
    fn fcitx5_rime_target_is_always_available() {
        let t = detect_fcitx5_rime();
        assert!(!t.user.as_os_str().is_empty());
        assert!(!t.shared.as_os_str().is_empty());
    }

    #[test]
    fn backend_default_reload_cmd() {
        assert_eq!(Backend::Xsime.default_reload_cmd(), None);
        assert_eq!(Backend::Fcitx5Rime.default_reload_cmd(), Some("fcitx5 -r"));
    }
}
