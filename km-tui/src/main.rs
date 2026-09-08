//! 空明码（kongmingma）方案词库管理 TUI
//!
//! 用法：
//!   km-tui                      # 启动目录树，默认根 = 上次目录 / 当前目录
//!   km-tui -D /path/to/rime     # 指定目录树根
//!   km-tui -d kongmingma.dict.yaml   # 跳过选择，直接打开某词库
//!   km-tui -p /path/to/luna_pinyin.dict.yaml   # 指定拼音数据源
//!
//! 依赖：本机需有 fcitx5-rime 与（拼音查询时）luna_pinyin 词典。

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
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(name = "km-tui", about = "空明码（kongmingma）方案词库管理 TUI")]
struct Cli {
    /// 直接打开指定词库（跳过选择界面）。
    #[arg(short = 'd', long = "dict")]
    dict: Option<PathBuf>,
    /// 目录树根目录（扫描其中的 kongming*.dict.yaml）。
    #[arg(short = 'D', long = "dir")]
    dir: Option<PathBuf>,
    /// luna_pinyin.dict.yaml 路径（拼音查询数据源）。
    #[arg(short = 'p', long = "pinyin")]
    pinyin: Option<PathBuf>,
}

fn main() -> Result<()> {
    color_eyre::install()?;

    let cli = Cli::parse();
    let config = config::Config::load();
    let deploy_cmd = deploy::detect_deploy_cmd(config.deploy_cmd.clone());
    let pinyin_path = cli
        .pinyin
        .or(config.pinyin_path.clone().map(PathBuf::from))
        .or_else(pinyin::find_luna_pinyin);
    let pinyin_map = pinyin_path.as_ref().and_then(|p| pinyin::load_pinyin_map(p));

    let root = cli
        .dir
        .or(config.last_dir.clone().map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("."));

    let mut app = if let Some(d) = cli.dict {
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
