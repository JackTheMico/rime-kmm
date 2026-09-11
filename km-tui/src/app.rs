use std::path::{Path, PathBuf};
use std::sync::mpsc::Receiver;

use crossterm::event::{Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};

use crate::deploy;
use crate::dict::{BuildMsg, Dict};
use crate::dirtree::DirTree;
use crate::encoder;
use crate::pinyin::PinyinMap;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Code,
    Pinyin,
    Word,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Query,
    Results,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum AddFocus {
    Word,
    Deductions,
    Code,
}

pub struct AddState {
    pub word: String,
    pub code: String,
    pub focus: AddFocus,
    pub deduced_codes: Vec<String>,
    pub selected_deduced: usize,
    pub same_codes: Vec<String>,
    pub is_exact_duplicate: bool,
    pub char_breakdown: Vec<(char, Vec<String>)>,
}

impl AddState {
    pub fn new() -> Self {
        AddState {
            word: String::new(),
            code: String::new(),
            focus: AddFocus::Word,
            deduced_codes: Vec::new(),
            selected_deduced: 0,
            same_codes: Vec::new(),
            is_exact_duplicate: false,
            char_breakdown: Vec::new(),
        }
    }

    pub fn on_word_changed(&mut self, dict: &Dict) {
        self.char_breakdown.clear();
        for ch in self.word.chars() {
            let list = dict.single_char_map.get(&ch).cloned().unwrap_or_default();
            self.char_breakdown.push((ch, list));
        }

        self.deduced_codes = encoder::deduce_codes(&dict.single_char_map, &self.word);
        self.selected_deduced = 0;
        if let Some(first) = self.deduced_codes.first() {
            self.code = first.clone();
        }
        self.on_code_changed(dict);
    }

    pub fn on_code_changed(&mut self, dict: &Dict) {
        let w = self.word.trim();
        let c = self.code.trim();
        if c.is_empty() {
            self.same_codes.clear();
            self.is_exact_duplicate = false;
            return;
        }
        match dict.check_add(w, c) {
            Ok(same) => {
                self.same_codes = same;
                self.is_exact_duplicate = false;
            }
            Err(_) => {
                self.same_codes.clear();
                self.is_exact_duplicate = true;
            }
        }
    }
}

pub enum Popup {
    None,
    Add(Box<AddState>),
    ConfirmDeploy { on_exit: bool },
    ConfirmDelete {
        entry_idx: u32,
        word: String,
        code: String,
        same_code_count: usize,
        rank: usize,
    },
    DeployLog(String),
    SwitchDict(DirTree),
    Message(String),
    Help,
}

pub enum Stage {
    Pick,
    Ready,
}

pub struct App {
    pub stage: Stage,
    pub dir_tree: DirTree,
    pub dict: Dict,
    pub dict_name: String,
    pub pinyin_map: Option<PinyinMap>,
    pub should_quit: bool,

    pub query: String,
    pub mode: Mode,
    pub focus: Focus,
    pub results: Vec<u32>,
    pub selected: usize,
    pub status: String,

    pub popup: Popup,
    pub pinyin_rx: Option<Receiver<BuildMsg>>,
    pub deploy_cmd: String,
    pub session_modified: bool,
    pub last_key_g: bool,
}

impl App {
    pub fn pick(root: PathBuf, deploy_cmd: String, pinyin_map: Option<PinyinMap>) -> App {
        App {
            stage: Stage::Pick,
            dir_tree: DirTree::new(root),
            dict: Dict::empty(),
            dict_name: String::new(),
            pinyin_map,
            should_quit: false,
            query: String::new(),
            mode: Mode::Code,
            focus: Focus::Results,
            results: Vec::new(),
            selected: 0,
            status: "j/k 移动 · l/Enter 打开 · h 返回上级 · q 退出".into(),
            popup: Popup::None,
            pinyin_rx: None,
            deploy_cmd,
            session_modified: false,
            last_key_g: false,
        }
    }

    pub fn with_dict(d: Dict, deploy_cmd: String, pinyin_map: Option<PinyinMap>) -> App {
        let name = d
            .path
            .file_name()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default();
        let root = d
            .path
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."));

        let mut app = App::pick(root, deploy_cmd, pinyin_map);
        app.dict = d;
        app.dict_name = name;
        app.stage = Stage::Ready;
        app.start_pinyin();
        app.status = "Normal 模式: j/k 移动 · J/K 调序 · H/L 置顶/底 · x 删除 · / 检索 · a 添加 · o 换库 · d 部署 · q 退出".into();
        app
    }

    fn start_pinyin(&mut self) {
        if self.pinyin_map.is_some() {
            if let Some(rx) = self.dict.start_pinyin_build() {
                self.pinyin_rx = Some(rx);
                self.status = "正在后台构建拼音索引…".into();
            }
        }
    }

    pub fn run(
        &mut self,
        terminal: &mut ratatui::Terminal<ratatui::backend::CrosstermBackend<std::io::Stdout>>,
    ) -> std::result::Result<(), Box<dyn std::error::Error>> {
        use crossterm::event::{poll, read};
        use std::time::Duration;
        loop {
            if matches!(self.stage, Stage::Ready) {
                self.poll_pinyin();
                self.dict.poll_save();
            }
            terminal.draw(|f| crate::ui::ui(f, self))?;
            if poll(Duration::from_millis(60))? {
                if let Ok(ev) = read() {
                    if let Event::Key(k) = ev {
                        if k.kind == KeyEventKind::Press {
                            self.handle(k);
                        }
                    }
                }
            }
            if self.should_quit {
                // 退出前强制落盘未保存修改
                let _ = self.dict.flush_sync();
                return Ok(());
            }
        }
    }

    fn handle(&mut self, k: KeyEvent) {
        match self.stage {
            Stage::Pick => self.handle_pick(k),
            Stage::Ready => {
                if !matches!(self.popup, Popup::None) {
                    self.handle_popup(k);
                } else {
                    self.handle_key(k);
                }
            }
        }
    }

    fn handle_pick(&mut self, k: KeyEvent) {
        let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
        if ctrl && k.code == KeyCode::Char('d') {
            self.dir_tree.move_sel(10);
            return;
        }
        if ctrl && k.code == KeyCode::Char('u') {
            self.dir_tree.move_sel(-10);
            return;
        }

        match k.code {
            KeyCode::Up | KeyCode::Char('k') => {
                self.last_key_g = false;
                self.dir_tree.move_sel(-1);
            }
            KeyCode::Down | KeyCode::Char('j') => {
                self.last_key_g = false;
                self.dir_tree.move_sel(1);
            }
            KeyCode::Char('g') => {
                if self.last_key_g {
                    self.dir_tree.selected = 0;
                    self.last_key_g = false;
                } else {
                    self.last_key_g = true;
                }
            }
            KeyCode::Char('G') => {
                self.last_key_g = false;
                if !self.dir_tree.flat.is_empty() {
                    self.dir_tree.selected = self.dir_tree.flat.len() - 1;
                }
            }
            KeyCode::Right | KeyCode::Char('l') | KeyCode::Enter | KeyCode::Char(' ') => {
                self.last_key_g = false;
                if let Some(path) = self.dir_tree.enter() {
                    self.load_dict(&path);
                }
            }
            KeyCode::Left | KeyCode::Char('h') | KeyCode::Backspace => {
                self.last_key_g = false;
                self.dir_tree.left();
            }
            KeyCode::Char('q') | KeyCode::Esc => {
                self.should_quit = true;
            }
            _ => {
                self.last_key_g = false;
            }
        }
    }

    pub fn load_dict(&mut self, path: &Path) {
        self.status = format!("正在加载 {}...", path.display());
        match Dict::load(path) {
            Ok(mut d) => {
                if let Some(m) = self.pinyin_map.clone() {
                    d.set_pinyin_map(m);
                }
                self.dict = d;
                self.dict_name = path
                    .file_name()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default();
                self.stage = Stage::Ready;
                self.query.clear();
                self.results.clear();
                self.selected = 0;
                self.focus = Focus::Results;
                self.session_modified = false;
                self.last_key_g = false;
                if let Some(parent) = path.parent() {
                    let mut c = crate::config::Config::load();
                    c.last_dir = Some(parent.to_string_lossy().into_owned());
                    c.save();
                }
                self.start_pinyin();
                self.status = format!(
                    "已加载词库「{}」（共 {} 条条目）。按 / 或 i 检索，j/k 移动，J/K 调序，x 删除。",
                    self.dict_name,
                    self.dict.len()
                );
            }
            Err(e) => {
                self.status = format!("加载词库失败：{e}");
            }
        }
    }

    fn handle_key(&mut self, k: KeyEvent) {
        let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
        let alt = k.modifiers.contains(KeyModifiers::ALT);

        match self.focus {
            Focus::Query => match k.code {
                KeyCode::Esc => self.focus = Focus::Results,
                KeyCode::Enter => {
                    self.run_search();
                    self.focus = Focus::Results;
                }
                KeyCode::Tab => self.cycle_mode(),
                KeyCode::Up => self.move_sel(-1),
                KeyCode::Down => self.move_sel(1),
                KeyCode::Backspace => {
                    self.query.pop();
                }
                KeyCode::Char(c) if !ctrl && !alt => {
                    self.query.push(c);
                }
                _ => {}
            },
            Focus::Results => {
                // Vim-like Candidate Reordering:
                // Shift+K / Alt+k / Alt+Up: candidate up (higher priority in Rime)
                // Shift+J / Alt+j / Alt+Down: candidate down
                // Shift+H / Alt+Home / Alt+T: candidate to top (first candidate)
                // Shift+L / Alt+End / Alt+B: candidate to bottom
                if k.code == KeyCode::Char('K')
                    || (alt && (k.code == KeyCode::Up || k.code == KeyCode::Char('k')))
                    || (ctrl && k.code == KeyCode::Char('k'))
                {
                    self.last_key_g = false;
                    self.reorder_candidate(-1);
                    return;
                }
                if k.code == KeyCode::Char('J')
                    || (alt && (k.code == KeyCode::Down || k.code == KeyCode::Char('j')))
                    || (ctrl && k.code == KeyCode::Char('j'))
                {
                    self.last_key_g = false;
                    self.reorder_candidate(1);
                    return;
                }
                if k.code == KeyCode::Char('H')
                    || (alt && (k.code == KeyCode::Home || k.code == KeyCode::Char('t') || k.code == KeyCode::Char('T')))
                {
                    self.last_key_g = false;
                    self.reorder_candidate_extreme(true);
                    return;
                }
                if k.code == KeyCode::Char('L')
                    || (alt && (k.code == KeyCode::End || k.code == KeyCode::Char('b') || k.code == KeyCode::Char('B')))
                {
                    self.last_key_g = false;
                    self.reorder_candidate_extreme(false);
                    return;
                }

                // Vim Page scrolling: Ctrl+d, Ctrl+u, Ctrl+f, Ctrl+b
                if ctrl && k.code == KeyCode::Char('d') {
                    self.last_key_g = false;
                    self.move_sel(10);
                    return;
                }
                if ctrl && k.code == KeyCode::Char('u') {
                    self.last_key_g = false;
                    self.move_sel(-10);
                    return;
                }
                if ctrl && k.code == KeyCode::Char('f') {
                    self.last_key_g = false;
                    self.move_sel(25);
                    return;
                }
                if ctrl && k.code == KeyCode::Char('b') {
                    self.last_key_g = false;
                    self.move_sel(-25);
                    return;
                }

                match k.code {
                    // Vim navigation
                    KeyCode::Up | KeyCode::Char('k') => {
                        self.last_key_g = false;
                        self.move_sel(-1);
                    }
                    KeyCode::Down | KeyCode::Char('j') => {
                        self.last_key_g = false;
                        self.move_sel(1);
                    }
                    KeyCode::Char('g') => {
                        if self.last_key_g {
                            self.selected = 0;
                            self.last_key_g = false;
                            self.status = "已跳转至结果首行 (gg)".into();
                        } else {
                            self.last_key_g = true;
                        }
                    }
                    KeyCode::Char('G') => {
                        self.last_key_g = false;
                        if !self.results.is_empty() {
                            self.selected = self.results.len() - 1;
                            self.status = "已跳转至结果末行 (G)".into();
                        }
                    }
                    KeyCode::Char('n') => {
                        self.last_key_g = false;
                        self.move_sel(1);
                    }
                    KeyCode::Char('N') => {
                        self.last_key_g = false;
                        self.move_sel(-1);
                    }
                    KeyCode::PageUp => {
                        self.last_key_g = false;
                        self.move_sel(-10);
                    }
                    KeyCode::PageDown => {
                        self.last_key_g = false;
                        self.move_sel(10);
                    }

                    // Search & Input modes
                    KeyCode::Char('/') | KeyCode::Char('i') => {
                        self.last_key_g = false;
                        self.focus = Focus::Query;
                    }
                    KeyCode::Char('a') => {
                        self.last_key_g = false;
                        let mut state = AddState::new();
                        if self.mode == Mode::Word && !self.query.is_empty() {
                            state.word = self.query.trim().to_string();
                            state.on_word_changed(&self.dict);
                        }
                        self.popup = Popup::Add(Box::new(state));
                    }
                    KeyCode::Char('x') | KeyCode::Delete => {
                        self.last_key_g = false;
                        self.prompt_delete_selected();
                    }

                    // File & Deployment Actions
                    KeyCode::Char('o') => {
                        self.last_key_g = false;
                        let root = self
                            .dict
                            .path
                            .parent()
                            .map(|p| p.to_path_buf())
                            .unwrap_or_else(|| PathBuf::from("."));
                        self.popup = Popup::SwitchDict(DirTree::new(root));
                    }
                    KeyCode::Char('d') => {
                        self.last_key_g = false;
                        self.popup = Popup::ConfirmDeploy { on_exit: false };
                    }
                    KeyCode::Char('w') => {
                        self.last_key_g = false;
                        self.save_immediate();
                    }
                    KeyCode::Char('s') if ctrl => {
                        self.last_key_g = false;
                        self.save_immediate();
                    }
                    KeyCode::Char('r') if ctrl => {
                        self.last_key_g = false;
                        self.popup = Popup::ConfirmDeploy { on_exit: false };
                    }
                    KeyCode::Char('q') | KeyCode::Esc => {
                        self.last_key_g = false;
                        self.request_quit();
                    }
                    KeyCode::Char('c') if ctrl => {
                        self.last_key_g = false;
                        self.request_quit();
                    }
                    KeyCode::Enter => {
                        self.last_key_g = false;
                        self.run_search();
                    }
                    KeyCode::Tab => {
                        self.last_key_g = false;
                        self.cycle_mode();
                    }
                    KeyCode::Char('?') | KeyCode::F(1) => {
                        self.last_key_g = false;
                        self.popup = Popup::Help;
                    }
                    _ => {
                        self.last_key_g = false;
                    }
                }
            }
        }
    }

    fn handle_popup(&mut self, k: KeyEvent) {
        let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
        let alt = k.modifiers.contains(KeyModifiers::ALT);

        match &mut self.popup {
            Popup::Add(state) => match state.focus {
                AddFocus::Word => match k.code {
                    KeyCode::Esc => self.popup = Popup::None,
                    KeyCode::Tab => {
                        if !state.deduced_codes.is_empty() {
                            state.focus = AddFocus::Deductions;
                        } else {
                            state.focus = AddFocus::Code;
                        }
                    }
                    KeyCode::Enter => {
                        if !state.code.is_empty() {
                            self.submit_add();
                        } else {
                            state.focus = AddFocus::Code;
                        }
                    }
                    KeyCode::Backspace => {
                        state.word.pop();
                        state.on_word_changed(&self.dict);
                    }
                    KeyCode::Char(c) if !ctrl && !alt => {
                        state.word.push(c);
                        state.on_word_changed(&self.dict);
                    }
                    _ => {}
                },
                AddFocus::Deductions => match k.code {
                    KeyCode::Esc | KeyCode::Char('h') => {
                        state.focus = AddFocus::Word;
                    }
                    KeyCode::Tab => state.focus = AddFocus::Code,
                    KeyCode::Up | KeyCode::Char('k') => {
                        if state.selected_deduced > 0 {
                            state.selected_deduced -= 1;
                            state.code = state.deduced_codes[state.selected_deduced].clone();
                            state.on_code_changed(&self.dict);
                        }
                    }
                    KeyCode::Down | KeyCode::Char('j') => {
                        if state.selected_deduced + 1 < state.deduced_codes.len() {
                            state.selected_deduced += 1;
                            state.code = state.deduced_codes[state.selected_deduced].clone();
                            state.on_code_changed(&self.dict);
                        }
                    }
                    KeyCode::Enter | KeyCode::Char(' ') | KeyCode::Char('l') => {
                        state.focus = AddFocus::Code;
                    }
                    _ => {}
                },
                AddFocus::Code => match k.code {
                    KeyCode::Esc => self.popup = Popup::None,
                    KeyCode::Tab => state.focus = AddFocus::Word,
                    KeyCode::Enter => self.submit_add(),
                    KeyCode::Backspace => {
                        state.code.pop();
                        state.on_code_changed(&self.dict);
                    }
                    KeyCode::Char(c) if !ctrl && !alt => {
                        state.code.push(c);
                        state.on_code_changed(&self.dict);
                    }
                    _ => {}
                },
            },
            Popup::ConfirmDeploy { on_exit } => {
                let is_exit = *on_exit;
                match k.code {
                    KeyCode::Char('y') | KeyCode::Char('Y') | KeyCode::Enter => {
                        let _ = self.dict.flush_sync();
                        let log = deploy::sync_and_deploy(&self.dict.path, Some(&self.deploy_cmd));
                        if is_exit {
                            self.popup = Popup::DeployLog(format!("{log}\n\n[按任意键退出程序]"));
                            self.should_quit = false; // 用户看一眼部署日志后再退
                        } else {
                            self.popup = Popup::DeployLog(log);
                        }
                    }
                    KeyCode::Char('n') | KeyCode::Char('N') => {
                        if is_exit {
                            let _ = self.dict.flush_sync();
                            self.should_quit = true;
                        } else {
                            self.popup = Popup::None;
                        }
                    }
                    KeyCode::Esc | KeyCode::Char('q') => {
                        self.popup = Popup::None;
                    }
                    _ => {}
                }
            }
            Popup::DeployLog(_) => match k.code {
                KeyCode::Esc | KeyCode::Enter | KeyCode::Char('q') | KeyCode::Char(' ') => {
                    if self.session_modified {
                        self.should_quit = true;
                    } else {
                        self.popup = Popup::None;
                    }
                }
                _ => {}
            },
            Popup::SwitchDict(tree) => {
                if ctrl && k.code == KeyCode::Char('d') {
                    tree.move_sel(10);
                    return;
                }
                if ctrl && k.code == KeyCode::Char('u') {
                    tree.move_sel(-10);
                    return;
                }
                match k.code {
                    KeyCode::Up | KeyCode::Char('k') => tree.move_sel(-1),
                    KeyCode::Down | KeyCode::Char('j') => tree.move_sel(1),
                    KeyCode::Right | KeyCode::Char('l') | KeyCode::Enter | KeyCode::Char(' ') => {
                        if let Some(path) = tree.enter() {
                            let _ = self.dict.flush_sync();
                            self.load_dict(&path);
                            self.popup = Popup::None;
                        }
                    }
                    KeyCode::Left | KeyCode::Char('h') | KeyCode::Backspace => tree.left(),
                    KeyCode::Char('g') => {
                        tree.selected = 0;
                    }
                    KeyCode::Char('G') => {
                        if !tree.flat.is_empty() {
                            tree.selected = tree.flat.len() - 1;
                        }
                    }
                    KeyCode::Esc | KeyCode::Char('o') | KeyCode::Char('q') => {
                        self.popup = Popup::None;
                    }
                    _ => {}
                }
            },
            Popup::ConfirmDelete { entry_idx, .. } => {
                let target_idx = *entry_idx;
                match k.code {
                    KeyCode::Char('y') | KeyCode::Char('Y') | KeyCode::Enter => {
                        self.popup = Popup::None;
                        self.execute_delete(target_idx);
                    }
                    KeyCode::Char('n') | KeyCode::Char('N') | KeyCode::Esc | KeyCode::Char('q') => {
                        self.popup = Popup::None;
                    }
                    _ => {}
                }
            }
            Popup::Help | Popup::Message(_) => match k.code {
                KeyCode::Esc | KeyCode::Enter | KeyCode::Char('q') | KeyCode::Char(' ') => {
                    self.popup = Popup::None;
                }
                _ => {}
            },
            Popup::None => {}
        }
    }

    fn submit_add(&mut self) {
        let (word, code) = match &self.popup {
            Popup::Add(state) => (state.word.trim().to_string(), state.code.trim().to_string()),
            _ => return,
        };

        if word.is_empty() || code.is_empty() {
            self.popup = Popup::Message("字词与编码均不能为空。".into());
            return;
        }

        match self.dict.check_add(&word, &code) {
            Err(e) => {
                self.popup = Popup::Message(e);
            }
            Ok(same_codes) => {
                let new_idx = self.dict.append_entry(&word, &code);
                self.session_modified = true;
                self.popup = Popup::None;

                // 将新增条目加入当前结果并聚焦
                self.results.insert(0, new_idx);
                self.selected = 0;
                self.focus = Focus::Results;

                if same_codes.is_empty() {
                    self.status = format!("✔ 已添加新条目：{word}\t{code}（独占首选，已实时调度保存）");
                } else {
                    self.status = format!(
                        "✔ 已添加新条目：{word}\t{code}（重码候选项：{}，位次：第 {} 位）",
                        same_codes.join("、"),
                        same_codes.len() + 1
                    );
                }
            }
        }
    }

    fn prompt_delete_selected(&mut self) {
        if self.results.is_empty() || self.selected >= self.results.len() {
            return;
        }
        let entry_idx = self.results[self.selected];
        let word = self.dict.word(entry_idx).to_string();
        let code = self.dict.code(entry_idx).to_string();
        let (rank, same_code_count) = self.dict.candidate_rank(entry_idx).unwrap_or((1, 1));
        self.popup = Popup::ConfirmDelete {
            entry_idx,
            word,
            code,
            same_code_count,
            rank,
        };
    }

    fn execute_delete(&mut self, entry_idx: u32) {
        if let Some((word, code)) = self.dict.delete_entry(entry_idx) {
            self.session_modified = true;
            if !self.results.is_empty()
                && self.selected < self.results.len()
                && self.results[self.selected] == entry_idx
            {
                self.results.remove(self.selected);
            } else {
                self.results.retain(|&x| x != entry_idx);
            }
            if self.results.is_empty() {
                self.selected = 0;
            } else if self.selected >= self.results.len() {
                self.selected = self.results.len() - 1;
            }
            self.status = format!(
                "✔ 已删除条目「{word}  {code}」（后台已调度防抖保存，.bak 已备份）"
            );
        }
    }

    fn request_quit(&mut self) {
        if self.session_modified || self.dict.dirty || self.dict.is_saving {
            self.popup = Popup::ConfirmDeploy { on_exit: true };
        } else {
            self.should_quit = true;
        }
    }

    fn save_immediate(&mut self) {
        match self.dict.flush_sync() {
            Ok(()) => {
                self.status = format!("✔ 已立即落盘写入 {}（.bak 备份已更新）", self.dict_name);
            }
            Err(e) => {
                self.status = format!("✖ 落盘写入失败：{e}");
            }
        }
    }

    fn cycle_mode(&mut self) {
        self.mode = match self.mode {
            Mode::Code => Mode::Pinyin,
            Mode::Pinyin => Mode::Word,
            Mode::Word => Mode::Code,
        };
        self.status = format!("已切换至 [{}] 检索模式", self.mode_name());
    }

    pub fn mode_name(&self) -> &'static str {
        match self.mode {
            Mode::Code => "编码",
            Mode::Pinyin => "拼音",
            Mode::Word => "字词",
        }
    }

    fn run_search(&mut self) {
        let q = self.query.trim().to_string();
        if q.is_empty() {
            self.results.clear();
            return;
        }
        self.results = match self.mode {
            Mode::Code => self.dict.search_code(&q),
            Mode::Word => self.dict.search_word(&q),
            Mode::Pinyin => match self.dict.search_pinyin(&q) {
                Some(v) => v,
                None => {
                    self.status = "拼音索引仍在构建中，请稍候再试。".into();
                    return;
                }
            },
        };
        self.selected = 0;
        self.status = format!(
            "检索「{}」命中 {} 条（模式：{}）",
            q,
            self.results.len(),
            self.mode_name()
        );
    }

    fn move_sel(&mut self, d: isize) {
        if self.results.is_empty() {
            return;
        }
        let n = self.results.len() as isize;
        let s = (self.selected as isize + d).clamp(0, n - 1);
        self.selected = s as usize;
    }

    fn reorder_candidate(&mut self, delta: isize) {
        if self.results.is_empty() || self.selected >= self.results.len() {
            return;
        }
        let current_entry = self.results[self.selected];
        if let Some(new_entry) = self.dict.reorder_same_code(current_entry, delta) {
            self.results[self.selected] = new_entry;
            self.session_modified = true;
            if let Some((rank, total)) = self.dict.candidate_rank(new_entry) {
                self.status = format!(
                    "✔ 已调整重码候选顺位：当前词条排第 [{rank}/{total}]（后台已触发防抖保存）"
                );
            }
        }
    }

    fn reorder_candidate_extreme(&mut self, to_top: bool) {
        if self.results.is_empty() || self.selected >= self.results.len() {
            return;
        }
        let current_entry = self.results[self.selected];
        if let Some(new_entry) = self.dict.reorder_extreme(current_entry, to_top) {
            self.results[self.selected] = new_entry;
            self.session_modified = true;
            let action = if to_top { "置顶为首选" } else { "置底为末选" };
            if let Some((rank, total)) = self.dict.candidate_rank(new_entry) {
                self.status = format!(
                    "✔ 已将条目{action}：排第 [{rank}/{total}]（后台已触发防抖保存）"
                );
            }
        }
    }

    fn poll_pinyin(&mut self) {
        if let Some(rx) = self.pinyin_rx.as_ref() {
            loop {
                match rx.try_recv() {
                    Ok(BuildMsg::Done(idx)) => {
                        self.dict.pinyin_index = Some(idx);
                        self.pinyin_rx = None;
                        self.status = "拼音索引构建完成。".into();
                        break;
                    }
                    Err(std::sync::mpsc::TryRecvError::Empty) => break,
                    Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                        self.pinyin_rx = None;
                        break;
                    }
                }
            }
        }
    }
}
