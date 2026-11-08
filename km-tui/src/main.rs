//! 空明码（kongmingma）方案词库管理 TUI
//!
//! 用法：
//!   km-tui                      # 默认打开主库的 kongmingmas.dict.yaml
//!   km-tui -D /path/to/rime     # 指定目录树根
//!   km-tui -d kongmingmas.dict.yaml   # 指定要编辑的词库
//!   km-tui -p /path/to/luna_pinyin.dict.yaml   # 指定拼音数据源
//!
//! 部署目标：XSIME（犀术IME）当前生效的方案包；保存后按 `d` 同步词库并重启 fcitx5。

mod app;
mod config;
mod deploy;
mod dict;
mod dirtree;
mod encoder;
mod pinyin;
mod ui;

use clap::Parser;
use color_eyre::eyre::Result;
use std::path::{Path, PathBuf};

#[derive(Parser, Debug)]
#[command(name = "km-tui", about = "空明码（kongmingma）方案词库管理 TUI")]
struct Cli {
    /// 直接打开指定词库（跳过默认定位）。
    #[arg(short = 'd', long = "dict")]
    dict: Option<PathBuf>,
    /// 目录树根目录（扫描其中的 kongming*.dict.yaml）。
    #[arg(short = 'D', long = "dir")]
    dir: Option<PathBuf>,
    /// luna_pinyin.dict.yaml 路径（拼音查询数据源）。
    #[arg(short = 'p', long = "pinyin")]
    pinyin: Option<PathBuf>,
}

const DEFAULT_DICT: &str = "kongmingmas.dict.yaml";

/// 默认编辑空明码主库中的 kongmingmas；找不到再退回 XSIME 方案包内的副本。
fn default_dict(config: &config::Config) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(dir) = &config.master_dir {
        candidates.push(PathBuf::from(dir).join(DEFAULT_DICT));
    }
    // km-tui 位于主库仓库内，取其上级目录作为主库根
    if let Some(repo) = Path::new(env!("CARGO_MANIFEST_DIR")).parent() {
        candidates.push(repo.join(DEFAULT_DICT));
    }
    if let Some(x) = deploy::detect() {
        candidates.push(x.resources.join(DEFAULT_DICT));
    }
    candidates.into_iter().find(|p| p.is_file())
}

fn main() -> Result<()> {
    color_eyre::install()?;

    let cli = Cli::parse();
    let config = config::Config::load();
    let deploy_cmd = config
        .deploy_cmd
        .clone()
        .unwrap_or_else(|| "fcitx5 -r".to_string());
    let pinyin_path = cli
        .pinyin
        .or(config.pinyin_path.clone().map(PathBuf::from))
        .or_else(pinyin::find_luna_pinyin);
    let pinyin_map = pinyin_path.as_ref().and_then(|p| pinyin::load_pinyin_map(p));

    let root = cli
        .dir
        .or(config.last_dir.clone().map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("."));
    let dict_path = cli.dict.or_else(|| default_dict(&config));

    let mut app = if let Some(d) = dict_path {
        match dict::Dict::load(&d) {
            Ok(mut dd) => {
                if let Some(m) = pinyin_map.clone() {
                    dd.set_pinyin_map(m);
                }
                app::App::with_dict(dd, deploy_cmd, pinyin_map)
            }
            Err(e) => {
                eprintln!("加载词库失败：{e}");
                std::process::exit(1);
            }
        }
    } else {
        app::App::pick(root, deploy_cmd, pinyin_map)
    };

    ratatui::run(|term| app.run(term)).map_err(|e| color_eyre::eyre::eyre!("{e}"))?;
    Ok(())
}
