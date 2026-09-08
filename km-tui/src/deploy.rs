use std::path::{Path, PathBuf};
use std::process::Command;

/// 探测 Rime 用户数据目录（默认通常为 ~/.local/share/fcitx5/rime）
pub fn detect_rime_dir() -> Option<PathBuf> {
    if let Some(data) = dirs::data_dir() {
        let p = data.join("fcitx5/rime");
        if p.exists() && p.is_dir() {
            return Some(p);
        }
    }
    if let Some(home) = dirs::home_dir() {
        let p = home.join(".local/share/fcitx5/rime");
        if p.exists() && p.is_dir() {
            return Some(p);
        }
        let p2 = home.join(".config/fcitx5/rime");
        if p2.exists() && p2.is_dir() {
            return Some(p2);
        }
        let p3 = home.join(".local/share/rime");
        if p3.exists() && p3.is_dir() {
            return Some(p3);
        }
    }
    None
}

/// 探测 Rime 共享预设目录（/usr/share/rime-data 等）
pub fn detect_shared_dir() -> Option<PathBuf> {
    for path in [
        "/usr/share/rime-data",
        "/usr/local/share/rime-data",
        "/usr/share/rime",
    ] {
        let p = PathBuf::from(path);
        if p.exists() && p.is_dir() {
            return Some(p);
        }
    }
    None
}

/// 探测并选择一个可用的部署命令。
/// 顺序：用户覆盖 > rime_deployer > fcitx5-remote -r > fcitx5 -r
pub fn detect_deploy_cmd(override_cmd: Option<String>) -> String {
    if let Some(c) = override_cmd {
        return c;
    }
    for c in ["rime_deployer", "fcitx5-remote -r", "fcitx5 -r"] {
        let base = c.split_whitespace().next().unwrap_or(c);
        let probe = format!("command -v {base}");
        if Command::new("sh")
            .arg("-c")
            .arg(probe)
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return c.to_string();
        }
    }
    "fcitx5-remote -r".to_string()
}

/// 同步外部词库到 Rime 目录并执行重新部署
pub fn sync_and_deploy(dict_path: &Path, override_cmd: Option<&str>) -> String {
    let mut log = String::new();
    let rime_dir = detect_rime_dir();

    // 1. 同步词库文件（若不在 Rime 用户目录下）
    if let Some(r_dir) = &rime_dir {
        if let Some(file_name) = dict_path.file_name() {
            let target_path = r_dir.join(file_name);
            let need_sync = match (dict_path.canonicalize(), target_path.canonicalize()) {
                (Ok(p1), Ok(p2)) => p1 != p2,
                _ => true,
            };

            if need_sync && dict_path.exists() {
                match std::fs::copy(dict_path, &target_path) {
                    Ok(bytes) => {
                        log.push_str(&format!(
                            "✔ 同步词库到 Rime 目录：{} ({:.2} MB)\n",
                            target_path.display(),
                            bytes as f64 / 1_048_576.0
                        ));
                    }
                    Err(e) => {
                        log.push_str(&format!("✖ 同步词库失败：{e}\n"));
                    }
                }
            }
        }
    } else {
        log.push_str("ℹ 未检测到独立的 Rime 用户目录，跳过文件同步\n");
    }

    // 2. 执行编译与重载命令
    // 如果存在 rime_deployer，优先使用 rime_deployer 进行构建
    if let Some(r_dir) = &rime_dir {
        let has_deployer = Command::new("sh")
            .arg("-c")
            .arg("command -v rime_deployer")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);

        if has_deployer {
            let shared_arg = match detect_shared_dir() {
                Some(s) => format!(" \"{}\"", s.display()),
                None => String::new(),
            };
            let cmd_str = format!("rime_deployer --build \"{}\"{}", r_dir.display(), shared_arg);
            log.push_str(&format!("⚙ 执行：{cmd_str}\n"));
            match Command::new("sh").arg("-c").arg(&cmd_str).output() {
                Ok(o) => {
                    let out = String::from_utf8_lossy(&o.stdout);
                    let err = String::from_utf8_lossy(&o.stderr);
                    if o.status.success() {
                        log.push_str("✔ Rime 部署构建成功\n");
                    } else {
                        log.push_str(&format!("✖ 部署构建返回异常码：{:?}\n{out}{err}\n", o.status.code()));
                    }
                }
                Err(e) => {
                    log.push_str(&format!("✖ 执行 rime_deployer 出错：{e}\n"));
                }
            }
        }
    }

    // 3. 通知 fcitx5 重新加载 (fcitx5-remote -r)
    let reload_cmd = override_cmd.unwrap_or("fcitx5-remote -r");
    log.push_str(&format!("⚙ 重新加载：{reload_cmd}\n"));
    match Command::new("sh").arg("-c").arg(reload_cmd).output() {
        Ok(o) => {
            let out = String::from_utf8_lossy(&o.stdout);
            let err = String::from_utf8_lossy(&o.stderr);
            if o.status.success() {
                log.push_str("✔ fcitx5 重新加载信号发送成功\n");
            } else {
                log.push_str(&format!("⚠ 重新加载异常：{:?}\n{out}{err}\n", o.status.code()));
            }
        }
        Err(e) => {
            log.push_str(&format!("✖ 执行加载命令失败：{e}\n"));
        }
    }

    log
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_dirs() {
        let rime_dir = detect_rime_dir();
        assert!(rime_dir.is_some());
        let shared_dir = detect_shared_dir();
        assert!(shared_dir.is_some());
    }
}
