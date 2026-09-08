use std::collections::HashMap;

/// 单字编码表：每个单字可能有一个或多个编码（如简码、全码）
pub type SingleCharMap = HashMap<char, Vec<String>>;

/// 从给定的单字编码表中，为指定的词组推导推荐候选编码。
///
/// 经典形码构码规则：
/// - 2字词：
///   - 1+1: 各字第1码（如 "ab"）
///   - 2+2: 各字前2码（若长度不足则取全部，如 "abcd"）
/// - 3字词：
///   - 1+1+1: 前三字各取第1码
/// - 4字及以上词：
///   - 1+1+1+末1: 前三字各取第1码 + 末字第1码
///
/// 若单字存在多码，将按重要程度生成多组备选排列。
pub fn deduce_codes(char_map: &SingleCharMap, word: &str) -> Vec<String> {
    let chars: Vec<char> = word.chars().collect();
    if chars.is_empty() {
        return Vec::new();
    }

    if chars.len() == 1 {
        return char_map.get(&chars[0]).cloned().unwrap_or_default();
    }

    // 检查是否所有字都在单字表中
    for ch in &chars {
        if !char_map.contains_key(ch) {
            return Vec::new();
        }
    }

    let mut results = Vec::new();

    if chars.len() == 2 {
        let codes0 = &char_map[&chars[0]];
        let codes1 = &char_map[&chars[1]];

        // 1+1 规则
        for c0 in codes0 {
            for c1 in codes1 {
                if let (Some(s0), Some(s1)) = (c0.chars().next(), c1.chars().next()) {
                    let cand = format!("{s0}{s1}");
                    if !results.contains(&cand) {
                        results.push(cand);
                    }
                }
            }
        }

        // 2+2 规则
        for c0 in codes0 {
            for c1 in codes1 {
                let p0: String = c0.chars().take(2).collect();
                let p1: String = c1.chars().take(2).collect();
                if !p0.is_empty() && !p1.is_empty() {
                    let cand = format!("{p0}{p1}");
                    if !results.contains(&cand) {
                        results.push(cand);
                    }
                }
            }
        }
    } else if chars.len() == 3 {
        let codes0 = &char_map[&chars[0]];
        let codes1 = &char_map[&chars[1]];
        let codes2 = &char_map[&chars[2]];

        for c0 in codes0 {
            for c1 in codes1 {
                for c2 in codes2 {
                    if let (Some(s0), Some(s1), Some(s2)) =
                        (c0.chars().next(), c1.chars().next(), c2.chars().next())
                    {
                        let cand = format!("{s0}{s1}{s2}");
                        if !results.contains(&cand) {
                            results.push(cand);
                        }
                    }
                }
            }
        }
    } else {
        // 4字及以上词：前三字各取首码 + 末字首码
        let codes0 = &char_map[&chars[0]];
        let codes1 = &char_map[&chars[1]];
        let codes2 = &char_map[&chars[2]];
        let codes_last = &char_map[&chars[chars.len() - 1]];

        for c0 in codes0 {
            for c1 in codes1 {
                for c2 in codes2 {
                    for cl in codes_last {
                        if let (Some(s0), Some(s1), Some(s2), Some(sl)) = (
                            c0.chars().next(),
                            c1.chars().next(),
                            c2.chars().next(),
                            cl.chars().next(),
                        ) {
                            let cand = format!("{s0}{s1}{s2}{sl}");
                            if !results.contains(&cand) {
                                results.push(cand);
                            }
                        }
                    }
                }
            }
        }
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_deduce_2_chars() {
        let mut map = SingleCharMap::new();
        map.insert('空', vec!["km".into(), "k".into()]);
        map.insert('明', vec!["mn".into()]);

        let deduced = deduce_codes(&map, "空明");
        assert!(deduced.contains(&"km".into())); // 1+1 (k + m)
        assert!(deduced.contains(&"kmmn".into())); // 2+2 (km + mn)
    }

    #[test]
    fn test_deduce_3_chars() {
        let mut map = SingleCharMap::new();
        map.insert('中', vec!["z".into()]);
        map.insert('州', vec!["j".into()]);
        map.insert('韵', vec!["y".into()]);

        let deduced = deduce_codes(&map, "中州韵");
        assert_eq!(deduced, vec!["zjy".to_string()]);
    }
}
