use std::collections::HashMap;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::thread;
use std::time::Instant;

use crate::encoder::SingleCharMap;
use crate::pinyin::{word_to_pinyin, PinyinMap};

/// 后台拼音索引构建的消息。
pub enum BuildMsg {
    Done(HashMap<String, Vec<u32>>),
}

/// 后台保存任务载荷
struct SavePayload {
    path: PathBuf,
    header: Arc<String>,
    buffer: Arc<String>,
    appended: Arc<String>,
    entries: Arc<Vec<EntryRef>>,
}

/// 后台保存完成回传消息
pub enum SaveResult {
    Success(Instant),
    Failed(String),
}

#[derive(Clone, Copy, Debug)]
pub struct EntryRef {
    pub buf_id: u8, // 0 = 主文件 buffer, 1 = 追加 buffer
    pub ws: u32,
    pub we: u32,
    pub cs: u32,
    pub ce: u32,
}

/// RIME 词库管理核心
pub struct Dict {
    pub path: PathBuf,
    pub header: Arc<String>,
    pub buffer: Arc<String>,
    pub appended_buffer: Arc<String>,
    pub entries: Arc<Vec<EntryRef>>,

    /// code -> [entry_index]
    pub code_index: HashMap<String, Vec<u32>>,
    /// exact word -> [entry_index]
    pub word_index: HashMap<String, Vec<u32>>,
    /// 单字 -> [code] 映射，用于形码推导
    pub single_char_map: SingleCharMap,

    pub pinyin_map: Option<PinyinMap>,
    pub pinyin_index: Option<HashMap<String, Vec<u32>>>,

    // 脏标记与保存状态
    pub dirty: bool,
    pub last_modified: Option<Instant>,
    pub is_saving: bool,
    pub last_saved: Option<Instant>,

    save_tx: Option<Sender<SavePayload>>,
    save_rx: Option<Receiver<SaveResult>>,
}

impl Dict {
    pub fn empty() -> Dict {
        Dict {
            path: PathBuf::new(),
            header: Arc::new(String::new()),
            buffer: Arc::new(String::new()),
            appended_buffer: Arc::new(String::new()),
            entries: Arc::new(Vec::new()),
            code_index: HashMap::new(),
            word_index: HashMap::new(),
            single_char_map: HashMap::new(),
            pinyin_map: None,
            pinyin_index: None,
            dirty: false,
            last_modified: None,
            is_saving: false,
            last_saved: None,
            save_tx: None,
            save_rx: None,
        }
    }

    pub fn load(path: &Path) -> std::io::Result<Dict> {
        let buffer = std::fs::read_to_string(path)?;
        let buf = buffer.as_str();
        let mut header = String::new();
        let mut entries: Vec<EntryRef> = Vec::new();
        let mut pos = 0usize;
        let mut in_yaml_frontmatter = false;
        let mut header_ended = false;

        let mut code_index: HashMap<String, Vec<u32>> = HashMap::new();
        let mut word_index: HashMap<String, Vec<u32>> = HashMap::new();
        let mut single_char_map: SingleCharMap = HashMap::new();

        while pos < buf.len() {
            let line_end = match buf[pos..].find('\n') {
                Some(i) => pos + i,
                None => buf.len(),
            };
            let line = &buf[pos..line_end];
            let trimmed = line.trim();
            if !header_ended {
                if trimmed == "---" {
                    in_yaml_frontmatter = true;
                    header.push_str(line);
                    header.push('\n');
                    pos = line_end + 1;
                    continue;
                } else if in_yaml_frontmatter {
                    header.push_str(line);
                    header.push('\n');
                    if trimmed == "..." {
                        in_yaml_frontmatter = false;
                        header_ended = true;
                    }
                    pos = line_end + 1;
                    continue;
                } else if trimmed.is_empty() || trimmed.starts_with('#') {
                    header.push_str(line);
                    header.push('\n');
                    pos = line_end + 1;
                    continue;
                } else {
                    header_ended = true;
                }
            }

            if let Some(tab) = line.find('\t') {
                let ws = pos as u32;
                let we = (pos + tab) as u32;
                let cs = (pos + tab + 1) as u32;
                let ce = line_end as u32;

                let entry_idx = entries.len() as u32;
                entries.push(EntryRef {
                    buf_id: 0,
                    ws,
                    we,
                    cs,
                    ce,
                });

                let word = &buf[ws as usize..we as usize];
                let code = &buf[cs as usize..ce as usize];

                code_index
                    .entry(code.to_string())
                    .or_default()
                    .push(entry_idx);
                word_index
                    .entry(word.to_string())
                    .or_default()
                    .push(entry_idx);

                let mut char_iter = word.chars();
                if let Some(first_ch) = char_iter.next() {
                    if char_iter.next().is_none() {
                        // 单字条目
                        let list = single_char_map.entry(first_ch).or_default();
                        let code_str = code.to_string();
                        if !list.contains(&code_str) {
                            list.push(code_str);
                        }
                    }
                }
            }
            pos = line_end + 1;
        }

        let mut header = header;
        if !header.contains("---") || !header.contains("...") {
            let file_name = path.file_name().and_then(|s| s.to_str()).unwrap_or("dict");
            let dict_name = file_name.strip_suffix(".dict.yaml").unwrap_or(file_name);
            header = format!(
                "# Rime dictionary: {dict_name}\n# encoding: utf-8\n---\nname: {dict_name}\nversion: 2025/08/06\nsort: original\n...\n{header}"
            );
        }

        let (save_tx, save_rx) = Self::spawn_writer_thread();

        Ok(Dict {
            path: path.to_path_buf(),
            header: Arc::new(header),
            buffer: Arc::new(buffer),
            appended_buffer: Arc::new(String::new()),
            entries: Arc::new(entries),
            code_index,
            word_index,
            single_char_map,
            pinyin_map: None,
            pinyin_index: None,
            dirty: false,
            last_modified: None,
            is_saving: false,
            last_saved: None,
            save_tx: Some(save_tx),
            save_rx: Some(save_rx),
        })
    }

    fn spawn_writer_thread() -> (Sender<SavePayload>, Receiver<SaveResult>) {
        let (in_tx, in_rx) = channel::<SavePayload>();
        let (out_tx, out_rx) = channel::<SaveResult>();

        thread::spawn(move || {
            while let Ok(payload) = in_rx.recv() {
                // 执行实际写盘
                let res = Self::write_to_disk(&payload);
                match res {
                    Ok(()) => {
                        let _ = out_tx.send(SaveResult::Success(Instant::now()));
                    }
                    Err(e) => {
                        let _ = out_tx.send(SaveResult::Failed(e.to_string()));
                    }
                }
            }
        });

        (in_tx, out_rx)
    }

    fn write_to_disk(payload: &SavePayload) -> std::io::Result<()> {
        let bak = format!("{}.bak", payload.path.display());
        if payload.path.exists() {
            let _ = std::fs::copy(&payload.path, &bak);
        }

        let tmp_path = format!("{}.tmp.{}", payload.path.display(), std::process::id());
        {
            let file = File::create(&tmp_path)?;
            let mut writer = BufWriter::with_capacity(1024 * 1024, file);

            writer.write_all(payload.header.as_bytes())?;

            let b0 = payload.buffer.as_bytes();
            let b1 = payload.appended.as_bytes();

            for e in payload.entries.iter() {
                let (w_slice, c_slice) = if e.buf_id == 0 {
                    (&b0[e.ws as usize..e.we as usize], &b0[e.cs as usize..e.ce as usize])
                } else {
                    (&b1[e.ws as usize..e.we as usize], &b1[e.cs as usize..e.ce as usize])
                };
                writer.write_all(w_slice)?;
                writer.write_all(b"\t")?;
                writer.write_all(c_slice)?;
                writer.write_all(b"\n")?;
            }
            writer.flush()?;
        }

        std::fs::rename(&tmp_path, &payload.path)?;
        Ok(())
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn word(&self, i: u32) -> &str {
        let e = &self.entries[i as usize];
        if e.buf_id == 0 {
            &self.buffer[e.ws()..e.we()]
        } else {
            &self.appended_buffer[e.ws()..e.we()]
        }
    }

    pub fn code(&self, i: u32) -> &str {
        let e = &self.entries[i as usize];
        if e.buf_id == 0 {
            &self.buffer[e.cs()..e.ce()]
        } else {
            &self.appended_buffer[e.cs()..e.ce()]
        }
    }

    /// 获取指定编码下的所有候选项条目索引列表（严格对应文件原始排序）
    pub fn get_same_code_entries(&self, code: &str) -> Vec<u32> {
        self.code_index.get(code).cloned().unwrap_or_default()
    }

    /// 获取指定条目在其编码同码候选中的排位：`(rank_1_indexed, total_count)`
    pub fn candidate_rank(&self, entry_idx: u32) -> Option<(usize, usize)> {
        let code = self.code(entry_idx);
        let list = self.code_index.get(code)?;
        let pos = list.iter().position(|&x| x == entry_idx)?;
        Some((pos + 1, list.len()))
    }

    /// 在同码候选项中调整位次。
    /// delta: -1 上移，+1 下移。
    /// 返回新的条目索引。
    pub fn reorder_same_code(&mut self, entry_idx: u32, delta: isize) -> Option<u32> {
        let code = self.code(entry_idx).to_string();
        let list = match self.code_index.get(&code) {
            Some(l) => l.clone(),
            None => return None,
        };
        if list.len() < 2 {
            return Some(entry_idx);
        }

        let curr_pos = list.iter().position(|&x| x == entry_idx)?;
        let target_pos = curr_pos as isize + delta;
        if target_pos < 0 || target_pos >= list.len() as isize {
            return Some(entry_idx);
        }
        let target_pos = target_pos as usize;

        let entry_a = list[curr_pos];
        let entry_b = list[target_pos];

        // 物理交换词库中的条目位置
        let entries_mut = Arc::make_mut(&mut self.entries);
        entries_mut.swap(entry_a as usize, entry_b as usize);

        // 更新词库索引中的对应项
        // 注意：交换 entries 中的 a 和 b 内容后，原位置 entry_a 变成了 entry_b 的内容，原位置 entry_b 变成了 entry_a 的内容
        // 因此，原属于 entry_a 的字词现在位于物理索引 entry_b 处！
        self.rebuild_indices_for_entries(&[entry_a, entry_b]);

        self.dirty = true;
        self.last_modified = Some(Instant::now());

        Some(entry_b)
    }

    /// 将同码候选项直接置顶或置底
    pub fn reorder_extreme(&mut self, entry_idx: u32, to_top: bool) -> Option<u32> {
        let code = self.code(entry_idx).to_string();
        let list = match self.code_index.get(&code) {
            Some(l) => l.clone(),
            None => return None,
        };
        if list.len() < 2 {
            return Some(entry_idx);
        }

        let mut curr_idx = entry_idx;
        let mut curr_list = list;
        let target_rank = if to_top { 0 } else { curr_list.len() - 1 };

        while let Some(pos) = curr_list.iter().position(|&x| x == curr_idx) {
            if pos == target_rank {
                break;
            }
            let step = if to_top { -1 } else { 1 };
            if let Some(next_idx) = self.reorder_same_code(curr_idx, step) {
                curr_idx = next_idx;
                if let Some(nl) = self.code_index.get(&code) {
                    curr_list = nl.clone();
                } else {
                    break;
                }
            } else {
                break;
            }
        }

        Some(curr_idx)
    }

    fn rebuild_indices_for_entries(&mut self, indices: &[u32]) {
        for &idx in indices {
            let w = self.word(idx).to_string();
            let c = self.code(idx).to_string();

            // 更新 word_index
            if let Some(vec) = self.word_index.get_mut(&w) {
                if !vec.contains(&idx) {
                    vec.push(idx);
                    vec.sort_unstable();
                }
            }
            // 更新 code_index
            if let Some(vec) = self.code_index.get_mut(&c) {
                if !vec.contains(&idx) {
                    vec.push(idx);
                    vec.sort_unstable();
                }
            }
        }
    }

    /// 轮询后台保存状态，并在需要防抖落盘时派发任务
    pub fn poll_save(&mut self) {
        // 1. 检查是否有已完成的保存结果
        if let Some(rx) = &self.save_rx {
            while let Ok(res) = rx.try_recv() {
                self.is_saving = false;
                match res {
                    SaveResult::Success(t) => {
                        self.last_saved = Some(t);
                    }
                    SaveResult::Failed(_err) => {
                        // 保留 dirty 状态以便下次重试
                    }
                }
            }
        }

        // 2. 若有未落盘修改，且距离最后一次修改已过 300ms，派发保存任务
        if self.dirty && !self.is_saving {
            if let Some(mod_time) = self.last_modified {
                if mod_time.elapsed() >= std::time::Duration::from_millis(300) {
                    self.dispatch_save();
                }
            }
        }
    }

    /// 立即同步强制落盘（用于退出或部署前）
    pub fn flush_sync(&mut self) -> std::io::Result<()> {
        if !self.dirty {
            return Ok(());
        }
        let payload = SavePayload {
            path: self.path.clone(),
            header: Arc::clone(&self.header),
            buffer: Arc::clone(&self.buffer),
            appended: Arc::clone(&self.appended_buffer),
            entries: Arc::clone(&self.entries),
        };
        Self::write_to_disk(&payload)?;
        self.dirty = false;
        self.last_saved = Some(Instant::now());
        Ok(())
    }

    fn dispatch_save(&mut self) {
        if let Some(tx) = &self.save_tx {
            let payload = SavePayload {
                path: self.path.clone(),
                header: Arc::clone(&self.header),
                buffer: Arc::clone(&self.buffer),
                appended: Arc::clone(&self.appended_buffer),
                entries: Arc::clone(&self.entries),
            };
            if tx.send(payload).is_ok() {
                self.dirty = false;
                self.is_saving = true;
            }
        }
    }

    pub fn search_code(&self, q: &str) -> Vec<u32> {
        let ql = q.to_lowercase();
        let mut exact = Vec::new();
        let mut prefix = Vec::new();
        for (code, v) in self.code_index.iter() {
            if code.eq_ignore_ascii_case(&ql) {
                exact.extend_from_slice(v);
            } else if code.to_lowercase().starts_with(&ql) {
                prefix.extend_from_slice(v);
            }
        }
        exact.extend(prefix);
        exact
    }

    pub fn search_word(&self, q: &str) -> Vec<u32> {
        let ql = q.to_lowercase();
        let mut out = Vec::new();
        // 优先精确匹配
        if let Some(exact) = self.word_index.get(&ql) {
            out.extend_from_slice(exact);
        }
        // 其次包含匹配
        for (i, e) in self.entries.iter().enumerate() {
            let idx = i as u32;
            if out.contains(&idx) {
                continue;
            }
            let w = if e.buf_id == 0 {
                &self.buffer[e.ws()..e.we()]
            } else {
                &self.appended_buffer[e.ws()..e.we()]
            };
            if w.to_lowercase().contains(&ql) {
                out.push(idx);
                if out.len() >= 5000 {
                    break;
                }
            }
        }
        out
    }

    pub fn search_pinyin(&self, q: &str) -> Option<Vec<u32>> {
        let idx = self.pinyin_index.as_ref()?;
        let ql = q.to_lowercase();
        let mut exact: Vec<u32> = Vec::new();
        let mut prefix: Vec<u32> = Vec::new();
        for (py, v) in idx.iter() {
            if py == &ql {
                exact.extend_from_slice(v);
            } else if py.starts_with(&ql) {
                prefix.extend_from_slice(v);
            }
        }
        exact.extend(prefix);
        Some(exact)
    }

    /// 添加前查重：完全相同的「字词+编码」返回 Err；同编码返回同码词列表。
    pub fn check_add(&self, word: &str, code: &str) -> Result<Vec<String>, String> {
        let mut same_code = Vec::new();
        if let Some(entries) = self.code_index.get(code) {
            for &idx in entries {
                let w = self.word(idx);
                if w == word {
                    return Err(format!("已存在完全相同的条目：{word}\t{code}"));
                }
                same_code.push(w.to_string());
            }
        }
        Ok(same_code)
    }

    /// 追加新条目到末尾（零拷贝原文件缓冲区）。
    pub fn append_entry(&mut self, word: &str, code: &str) -> u32 {
        let appended_mut = Arc::make_mut(&mut self.appended_buffer);
        let start = appended_mut.len() as u32;
        appended_mut.push_str(word);
        let ws = start;
        let we = start + word.len() as u32;
        appended_mut.push('\t');
        let cs = we + 1;
        appended_mut.push_str(code);
        let ce = cs + code.len() as u32;
        appended_mut.push('\n');

        let new_idx = self.entries.len() as u32;
        let entries_mut = Arc::make_mut(&mut self.entries);
        entries_mut.push(EntryRef {
            buf_id: 1,
            ws,
            we,
            cs,
            ce,
        });

        self.code_index
            .entry(code.to_string())
            .or_default()
            .push(new_idx);
        self.word_index
            .entry(word.to_string())
            .or_default()
            .push(new_idx);

        let mut char_iter = word.chars();
        if let Some(first_ch) = char_iter.next() {
            if char_iter.next().is_none() {
                let list = self.single_char_map.entry(first_ch).or_default();
                let code_str = code.to_string();
                if !list.contains(&code_str) {
                    list.push(code_str);
                }
            }
        }

        if let Some(map) = &self.pinyin_map {
            if let Some(py) = word_to_pinyin(map, word) {
                if let Some(idx) = self.pinyin_index.as_mut() {
                    idx.entry(py).or_default().push(new_idx);
                }
            }
        }

        self.dirty = true;
        self.last_modified = Some(Instant::now());

        new_idx
    }

    pub fn set_pinyin_map(&mut self, m: PinyinMap) {
        self.pinyin_map = Some(m);
    }

    /// 后台构建拼音索引
    pub fn start_pinyin_build(&self) -> Option<Receiver<BuildMsg>> {
        let map = self.pinyin_map.clone()?;
        let entries = Arc::clone(&self.entries);
        let buffer = Arc::clone(&self.buffer);
        let appended = Arc::clone(&self.appended_buffer);
        let (tx, rx) = channel();

        thread::spawn(move || {
            let mut idx: HashMap<String, Vec<u32>> = HashMap::new();
            for (i, e) in entries.iter().enumerate() {
                let w = if e.buf_id == 0 {
                    &buffer[e.ws()..e.we()]
                } else {
                    &appended[e.ws()..e.we()]
                };
                if let Some(py) = word_to_pinyin(&map, w) {
                    idx.entry(py).or_default().push(i as u32);
                }
            }
            let _ = tx.send(BuildMsg::Done(idx));
        });
        Some(rx)
    }
}

// 辅助方法，简化切片访问
impl EntryRef {
    #[inline(always)]
    pub fn ws(&self) -> usize {
        self.ws as usize
    }
    #[inline(always)]
    pub fn we(&self) -> usize {
        self.we as usize
    }
    #[inline(always)]
    pub fn cs(&self) -> usize {
        self.cs as usize
    }
    #[inline(always)]
    pub fn ce(&self) -> usize {
        self.ce as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static TEST_COUNTER: AtomicUsize = AtomicUsize::new(0);

    fn create_temp_dict(content: &str) -> (tempfile_path::TempFile, PathBuf) {
        let dir = std::env::temp_dir();
        let count = TEST_COUNTER.fetch_add(1, Ordering::Relaxed);
        let path = dir.join(format!("test_dict_{}_{}.dict.yaml", std::process::id(), count));
        std::fs::write(&path, content).unwrap();
        (tempfile_path::TempFile(path.clone()), path)
    }

    mod tempfile_path {
        use std::path::PathBuf;
        pub struct TempFile(pub PathBuf);
        impl Drop for TempFile {
            fn drop(&mut self) {
                let _ = std::fs::remove_file(&self.0);
                let _ = std::fs::remove_file(format!("{}.bak", self.0.display()));
            }
        }
    }

    #[test]
    fn test_dict_load_and_reorder() {
        let content = "# Rime dict\n---\nname: test\nsort: original\n...\n视\ts=\n事\tS=\n世\ts=\n";
        let (_guard, path) = create_temp_dict(content);

        let mut dict = Dict::load(&path).unwrap();
        assert_eq!(dict.len(), 3);

        // 视 (0) 与 世 (2) 均对应 "s="
        let same = dict.get_same_code_entries("s=");
        assert_eq!(same, vec![0, 2]);

        // 当前 "视" 排第 1，"世" 排第 2
        assert_eq!(dict.candidate_rank(0), Some((1, 2)));
        assert_eq!(dict.candidate_rank(2), Some((2, 2)));

        // 将 "世" (2) 上移到第 1 候选
        let new_idx = dict.reorder_same_code(2, -1).unwrap();
        // 交换后，位于原索引 0 位置的现在是 "世"
        assert_eq!(dict.word(new_idx), "世");
        assert_eq!(dict.candidate_rank(new_idx), Some((1, 2)));

        // 落盘保存并验证文件文本
        dict.flush_sync().unwrap();
        let saved = std::fs::read_to_string(&path).unwrap();
        assert!(saved.contains("name: test"));
        assert!(saved.contains("sort: original"));
        let lines: Vec<&str> = saved.lines().filter(|l| l.contains('\t')).collect();
        assert_eq!(lines, vec!["世\ts=", "事\tS=", "视\ts="]);
    }

    #[test]
    fn test_check_add_and_append() {
        let content = "---\nname: test\n...\n视\ts=\n";
        let (_guard, path) = create_temp_dict(content);

        let mut dict = Dict::load(&path).unwrap();

        // 查重：完全相同应报错
        assert!(dict.check_add("视", "s=").is_err());

        // 同码不同词：返回重码列表
        let same = dict.check_add("事", "s=").unwrap();
        assert_eq!(same, vec!["视".to_string()]);

        // 追加
        let new_idx = dict.append_entry("事", "s=");
        assert_eq!(dict.word(new_idx), "事");
        assert_eq!(dict.code(new_idx), "s=");
        assert_eq!(dict.candidate_rank(new_idx), Some((2, 2)));

        dict.flush_sync().unwrap();
        let saved = std::fs::read_to_string(&path).unwrap();
        assert!(saved.contains("事\ts="));
    }

    #[test]
    fn test_reorder_extreme() {
        let content = "---\nname: test\n...\n甲\tkm\n乙\tkm\n丙\tkm\n丁\tkm\n";
        let (_guard, path) = create_temp_dict(content);

        let mut dict = Dict::load(&path).unwrap();
        assert_eq!(dict.len(), 4);

        // 丁 是第 4 候选 (索引 3)
        assert_eq!(dict.candidate_rank(3), Some((4, 4)));

        // 置顶 丁
        let top_idx = dict.reorder_extreme(3, true).unwrap();
        assert_eq!(dict.word(top_idx), "丁");
        assert_eq!(dict.candidate_rank(top_idx), Some((1, 4)));

        // 置底 丁
        let bottom_idx = dict.reorder_extreme(top_idx, false).unwrap();
        assert_eq!(dict.word(bottom_idx), "丁");
        assert_eq!(dict.candidate_rank(bottom_idx), Some((4, 4)));
    }
}
