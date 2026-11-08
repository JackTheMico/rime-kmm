use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// 单字 -> 拼音（无声调、小写）映射
pub type PinyinMap = HashMap<String, String>;

/// 把词（可能多字）转为连续拼音串；任一字缺拼音则返回 None。
pub fn word_to_pinyin(map: &PinyinMap, word: &str) -> Option<String> {
    let mut s = String::new();
    for ch in word.chars() {
        let key = ch.to_string();
        let py = map.get(&key)?;
        s.push_str(py);
    }
    Some(s)
}

/// 从 luna_pinyin.dict.yaml 构建单字拼音映射。
/// 每行格式：`单字<TAB>拼音 其它读音...`，取首个读音并去掉声调数字。
pub fn load_pinyin_map(path: &Path) -> Option<PinyinMap> {
    let text = std::fs::read_to_string(path).ok()?;
    let mut map = PinyinMap::new();
    for line in text.lines() {
        if line.starts_with('#') || line.trim().is_empty() {
            continue;
        }
        let mut parts = line.splitn(2, '\t');
        let ch = parts.next()?;
        let rest = parts.next()?;
        let reading = rest.split_whitespace().next().unwrap_or("");
        let cleaned: String = reading.chars().filter(|c| !c.is_ascii_digit()).collect();
        let lower = cleaned.to_lowercase();
        if !lower.is_empty() {
            map.entry(ch.to_string()).or_insert(lower);
        }
    }
    Some(map)
}

/// 自动查找 luna_pinyin.dict.yaml：优先 XSIME 当前方案包，其次系统 Rime 共享目录。
pub fn find_luna_pinyin() -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(x) = crate::deploy::detect() {
        candidates.push(x.resources.join("luna_pinyin.dict.yaml"));
    }
    candidates.push(PathBuf::from("/usr/share/rime-data/luna_pinyin.dict.yaml"));
    candidates.into_iter().find(|p| p.is_file())
}
