use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// 部署后端。决定词库同步到哪个 Rime 数据目录以及如何重载。
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Backend {
    /// XSIME（犀术IME）：同步到当前生效的方案包，由 librime 编译到 learning 目录。
    #[default]
    Xsime,
    /// fcitx5-rime：同步到用户 Rime 数据目录，编译后重载 fcitx5。
    Fcitx5Rime,
}

impl Backend {
    pub const ALL: [Backend; 2] = [Backend::Xsime, Backend::Fcitx5Rime];

    pub fn label(self) -> &'static str {
        match self {
            Backend::Xsime => "XSIME（犀术IME 方案包）",
            Backend::Fcitx5Rime => "fcitx5-rime（用户数据目录）",
        }
    }

    /// 未配置自定义重载命令时使用的默认值。
    pub fn default_reload_cmd(self) -> Option<&'static str> {
        match self {
            Backend::Xsime => None,
            Backend::Fcitx5Rime => Some("fcitx5 -r"),
        }
    }
}

/// 用户配置，持久化到 ~/.config/km-tui/config.json
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct Config {
    /// 上次成功打开词库所在的目录（下次启动目录树以此为根）
    pub last_dir: Option<String>,
    /// 用户覆盖的重新加载命令；留空时按所选后端使用内置流程
    pub deploy_cmd: Option<String>,
    /// luna_pinyin.dict.yaml 的显式路径
    pub pinyin_path: Option<String>,
    /// 空明码主库所在目录（默认取 km-tui 仓库根目录）
    pub master_dir: Option<String>,
    /// 部署后端（缺省为 XSIME，保持旧配置行为不变）
    pub backend: Backend,
}

impl Config {
    fn path() -> PathBuf {
        let mut d = dirs::config_dir().unwrap_or_else(|| PathBuf::from("."));
        d.push("km-tui");
        d.push("config.json");
        d
    }

    pub fn load() -> Config {
        let p = Config::path();
        if let Ok(s) = std::fs::read_to_string(&p) {
            serde_json::from_str(&s).unwrap_or_default()
        } else {
            Config::default()
        }
    }

    pub fn save(&self) {
        let p = Config::path();
        if let Some(parent) = p.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(s) = serde_json::to_string_pretty(self) {
            let _ = std::fs::write(&p, s);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn old_config_without_backend_defaults_to_xsime() {
        let c: Config = serde_json::from_str(r#"{"deploy_cmd":"echo hi"}"#).unwrap();
        assert_eq!(c.backend, Backend::Xsime);
        assert_eq!(c.deploy_cmd.as_deref(), Some("echo hi"));
    }

    #[test]
    fn backend_roundtrip() {
        let c: Config = serde_json::from_str(r#"{"backend":"fcitx5_rime"}"#).unwrap();
        assert_eq!(c.backend, Backend::Fcitx5Rime);
        let s = serde_json::to_string(&c).unwrap();
        assert!(s.contains("fcitx5_rime"));
    }
}
