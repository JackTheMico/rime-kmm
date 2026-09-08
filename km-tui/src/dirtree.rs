use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

/// 目录树中的一行可见条目。
#[derive(Clone)]
pub struct TreeRow {
    pub depth: usize,
    pub name: String,
    pub path: PathBuf,
    pub is_dir: bool,
    pub size: u64,
}

/// 可展开/收起的目录树，用于选择词库所在目录。
/// 懒加载：仅在展开目录时读取其子项并缓存。
pub struct DirTree {
    pub root: PathBuf,
    expanded: HashSet<PathBuf>,
    cache: HashMap<PathBuf, Vec<TreeRow>>,
    pub flat: Vec<TreeRow>,
    pub selected: usize,
}

impl DirTree {
    pub fn new(root: PathBuf) -> DirTree {
        let mut t = DirTree {
            root,
            expanded: HashSet::new(),
            cache: HashMap::new(),
            flat: Vec::new(),
            selected: 0,
        };
        t.expanded.insert(t.root.clone());
        t.rebuild();
        t
    }

    pub fn set_root(&mut self, root: PathBuf) {
        self.root = root;
        self.expanded.clear();
        self.cache.clear();
        self.expanded.insert(self.root.clone());
        self.rebuild();
        self.selected = 0;
    }

    fn ensure_loaded(&mut self, dir: &Path) -> Vec<TreeRow> {
        if let Some(v) = self.cache.get(dir) {
            return v.clone();
        }
        let mut rows = Vec::new();
        if let Ok(rd) = std::fs::read_dir(dir) {
            for e in rd.flatten() {
                let path = e.path();
                let meta = match e.metadata() {
                    Ok(m) => m,
                    Err(_) => continue,
                };
                let name = e.file_name().to_string_lossy().to_string();
                if meta.is_dir() {
                    rows.push(TreeRow {
                        depth: 0,
                        name,
                        path,
                        is_dir: true,
                        size: 0,
                    });
                } else if name.ends_with(".dict.yaml") {
                    rows.push(TreeRow {
                        depth: 0,
                        name,
                        path,
                        is_dir: false,
                        size: meta.len(),
                    });
                }
            }
        }
        rows.sort_by(|a, b| {
            if a.is_dir != b.is_dir {
                return b.is_dir.cmp(&a.is_dir); // 目录在前
            }
            let a_km = a.name.contains("kongming");
            let b_km = b.name.contains("kongming");
            if a_km != b_km {
                return b_km.cmp(&a_km); // kongming 词库优先
            }
            b.size.cmp(&a.size) // 体积大的在前
        });
        self.cache.insert(dir.to_path_buf(), rows.clone());
        rows
    }

    fn rebuild(&mut self) {
        self.flat.clear();
        if let Some(parent) = self.root.parent() {
            if !parent.as_os_str().is_empty() {
                self.flat.push(TreeRow {
                    depth: 0,
                    name: "..".into(),
                    path: parent.to_path_buf(),
                    is_dir: true,
                    size: 0,
                });
            }
        }
        let root = self.root.clone();
        let children = self.ensure_loaded(&root);
        self.collect(&children, 0);
        if self.selected >= self.flat.len() {
            self.selected = self.flat.len().saturating_sub(1);
        }
    }

    fn collect(&mut self, children: &[TreeRow], depth: usize) {
        for c in children {
            let mut row = c.clone();
            row.depth = depth;
            self.flat.push(row);
            if c.is_dir && self.expanded.contains(&c.path) {
                let sub = self.ensure_loaded(&c.path);
                self.collect(&sub, depth + 1);
            }
        }
    }

    /// 在当前行执行 Enter/→：目录则展开/收起；".." 则上移根；词库文件则返回其路径。
    pub fn enter(&mut self) -> Option<PathBuf> {
        let row = self.flat.get(self.selected)?.clone();
        if row.is_dir {
            if row.name == ".." {
                self.set_root(row.path.clone());
                return None;
            }
            if self.expanded.contains(&row.path) {
                self.expanded.remove(&row.path);
            } else {
                self.expanded.insert(row.path.clone());
            }
            self.rebuild();
            None
        } else {
            Some(row.path.clone())
        }
    }

    /// ←/Backspace：收起已展开目录，否则选中上移到父目录行。
    pub fn left(&mut self) {
        let row = match self.flat.get(self.selected).cloned() {
            Some(r) => r,
            None => return,
        };
        if row.is_dir && row.name != ".." && self.expanded.contains(&row.path) {
            self.expanded.remove(&row.path);
            self.rebuild();
            return;
        }
        if let Some(parent) = row.path.parent() {
            if let Some(idx) = self.flat.iter().position(|r| r.path == parent) {
                self.selected = idx;
                return;
            }
        }
        self.selected = 0;
    }

    pub fn move_sel(&mut self, d: isize) {
        if self.flat.is_empty() {
            return;
        }
        let n = self.flat.len() as isize;
        let s = (self.selected as isize + d).clamp(0, n - 1);
        self.selected = s as usize;
    }
}
