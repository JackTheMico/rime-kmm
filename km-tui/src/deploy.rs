use std::path::{Path, PathBuf};
use std::process::Command;

/// XSIME（犀术IME）在 Linux 上的运行时目录布局。
///
/// `resources`：当前生效的共享数据目录（导入方案包时是方案包目录，否则为内置 `data`）。
pub struct XSIME {
    pub resources: PathBuf,
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
            return Some(XSIME { resources, schema });
        }
    }

    // 未导入方案包时使用内置数据目录
    let resources = user_root.join("data");
    resources.is_dir().then_some(XSIME { resources, schema })
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

/// 把词库同步到 XSIME 当前方案包，再重启 fcitx5 让 XSIME 重新编译词库。
pub fn sync_and_deploy(dict_path: &Path, override_cmd: Option<&str>) -> String {
    let mut log = String::new();
    let Some(x) = detect() else {
        log.push_str("✖ 未检测到 XSIME 目录（~/.local/share/rimes），请确认已安装犀术IME\n");
        return log;
    };

    // 1. 同步词库到方案包（若当前编辑的已经就在方案目录内则跳过）
    let Some(name) = dict_path.file_name() else {
        log.push_str("✖ 词库路径缺少文件名，无法同步\n");
        return log;
    };
    let target = x.resources.join(name);
    let same = matches!(
        (dict_path.canonicalize(), target.canonicalize()),
        (Ok(a), Ok(b)) if a == b
    );
    if same {
        log.push_str("ℹ 词库已在 XSIME 方案目录内，无需同步\n");
    } else if dict_path.exists() {
        match std::fs::copy(dict_path, &target) {
            Ok(bytes) => log.push_str(&format!(
                "✔ 同步词库到 XSIME 方案目录：{} ({:.2} MB)\n",
                target.display(),
                bytes as f64 / 1_048_576.0
            )),
            Err(e) => log.push_str(&format!("✖ 同步词库失败：{e}\n")),
        }
    } else {
        log.push_str(&format!("✖ 词库不存在：{}\n", dict_path.display()));
    }

    // 2. 触发 XSIME 重新编译：默认重启 fcitx5，插件启动时自动部署
    let cmd = override_cmd.unwrap_or("fcitx5 -r");
    log.push_str(&format!(
        "⚙ 目标方案：{}（schema: {}）\n",
        x.resources.display(),
        x.schema.as_deref().unwrap_or("未知")
    ));
    log.push_str(&format!("⚙ 重新加载：{cmd}\n"));

    if is_fcitx5_restart(cmd) {
        if spawn_detached(cmd) {
            log.push_str("✔ 已请求重启 fcitx5；XSIME 启动时会在后台重编译词库\n");
            log.push_str("ℹ 编译完成前候选仍为旧内容，状态栏显示 Deploying 时请稍候\n");
        } else {
            log.push_str("✖ 无法启动 fcitx5，请手动重启输入法\n");
        }
    } else {
        match run_captured(cmd) {
            Ok(o) => {
                let out = String::from_utf8_lossy(&o.stdout);
                let err = String::from_utf8_lossy(&o.stderr);
                if o.status.success() {
                    log.push_str("✔ 自定义重载命令执行成功\n");
                } else {
                    log.push_str(&format!(
                        "⚠ 自定义重载命令返回异常码：{:?}\n{out}{err}\n",
                        o.status.code()
                    ));
                }
            }
            Err(e) => log.push_str(&format!("✖ 执行重载命令失败：{e}\n")),
        }
    }

    log
}

/// `fcitx5 -r` 会接管前台进程，必须脱离终端后台启动，否则会一直占用输出管道。
fn is_fcitx5_restart(cmd: &str) -> bool {
    cmd.split_whitespace()
        .next()
        .and_then(|bin| Path::new(bin).file_name())
        .and_then(|s| s.to_str())
        == Some("fcitx5")
}

fn spawn_detached(cmd: &str) -> bool {
    Command::new("sh")
        .arg("-c")
        .arg(format!("setsid {cmd} </dev/null >/dev/null 2>&1 &"))
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
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

    #[test]
    fn test_is_fcitx5_restart() {
        assert!(is_fcitx5_restart("fcitx5 -r"));
        assert!(is_fcitx5_restart("/usr/bin/fcitx5 --replace"));
        assert!(!is_fcitx5_restart("fcitx5-remote -r"));
    }
}
