use std::path::{Path, PathBuf};
use std::process::Command;

/// 需要跟随主词库一起同步到 XSIME 方案包的配套文件。
const COMPANIONS: &[&str] = &[
    "kongmingmas.schema.yaml",
    "kongmingmas_core.dict.yaml",
    "kongmingmas_ext.schema.yaml",
    "rime.lua",
];

/// XSIME（犀术IME）在 Linux 上的运行时目录布局。
///
/// `resources`：当前生效的共享数据目录（导入方案包时是方案包目录，否则为内置 `data`）。
/// `learning`：用户目录，部署产物（`build/*.table.bin`）写在这里。
pub struct XSIME {
    pub resources: PathBuf,
    pub learning: PathBuf,
    pub schema: Option<String>,
}

/// 探测 XSIME 当前生效的资源目录与用户目录。
/// 优先读取 `~/.local/share/rimes/schemes/active.yaml` 指向的导入方案包。
pub fn detect() -> Option<XSIME> {
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
            return Some(XSIME {
                resources,
                learning,
                schema,
            });
        }
    }

    // 未导入方案包时使用内置数据目录
    let data = user_root.join("data");
    data.is_dir().then(|| XSIME {
        resources: data.clone(),
        learning: data,
        schema,
    })
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

/// 把词库及其配套文件同步到 XSIME 方案包，然后编译。
/// `override_cmd` 为空时走内置部署（直接调用 librime）；非空时执行该命令。
pub fn sync_and_deploy(dict_path: &Path, override_cmd: Option<&str>) -> String {
    let mut log = String::new();
    let Some(x) = detect() else {
        log.push_str("✖ 未检测到 XSIME 目录（~/.local/share/rimes），请确认已安装犀术IME\n");
        return log;
    };
    let Some(name) = dict_path.file_name() else {
        log.push_str("✖ 词库路径缺少文件名，无法同步\n");
        return log;
    };
    let repo_root = dict_path.parent().unwrap_or(Path::new("."));

    // 1. 同步主词库
    let target = x.resources.join(name);
    if dict_path.exists() {
        match std::fs::copy(dict_path, &target) {
            Ok(bytes) => log.push_str(&format!(
                "✔ 同步词库：{} ({:.2} MB)\n",
                target.display(),
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
        let dst = x.resources.join(rel);
        if let Some(parent) = dst.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        match std::fs::copy(&src, &dst) {
            Ok(_) => log.push_str(&format!("✔ 同步 {rel}\n")),
            Err(e) => log.push_str(&format!("✖ 同步 {rel} 失败：{e}\n")),
        }
    }

    log.push_str(&format!(
        "⚙ 方案包：{}（schema: {}）\n⚙ 用户目录：{}\n",
        x.resources.display(),
        x.schema.as_deref().unwrap_or("未知"),
        x.learning.display()
    ));

    // 3. 编译
    match override_cmd.map(str::trim).filter(|s| !s.is_empty()) {
        Some(cmd) => run_custom(cmd, &mut log),
        None => run_builtin(&x, repo_root, &mut log),
    }

    log
}

fn run_custom(cmd: &str, log: &mut String) {
    log.push_str(&format!("⚙ 自定义重载命令：{cmd}\n"));
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

/// 内置部署：用 `tools/km_deploy.c` 直接调用 librime 编译到 XSIME 用户目录。
fn run_builtin(x: &XSIME, repo_root: &Path, log: &mut String) {
    let bin = match ensure_deployer(repo_root) {
        Ok(b) => b,
        Err(e) => {
            log.push_str(&format!("✖ 准备部署器失败：{e}\n"));
            return;
        }
    };
    log.push_str(&format!("⚙ 编译：{} + librime\n", bin.display()));
    match Command::new(&bin)
        .arg(&x.resources)
        .arg(&x.learning)
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
        let (package, schema) = parse_active(text);
        assert_eq!(package.as_deref(), Some("75f1c5dc30f81cbd685ed329027693c3"));
        assert_eq!(schema.as_deref(), Some("kongmingmas"));
    }

    #[test]
    fn test_parse_active_empty() {
        assert_eq!(parse_active(""), (None, None));
    }
}
