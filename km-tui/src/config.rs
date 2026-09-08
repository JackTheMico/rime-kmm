use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// 用户配置，持久化到 ~/.config/km-tui/config.json
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Config {
    /// 上次成功打开词库所在的目录（下次启动目录树以此为根）
    pub last_dir: Option<String>,
    /// 用户覆盖的重新部署命令
    pub deploy_cmd: Option<String>,
    /// luna_pinyin.dict.yaml 的显式路径
    pub pinyin_path: Option<String>,
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
