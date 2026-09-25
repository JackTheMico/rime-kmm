use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Clear, Paragraph, Row, Table, Wrap};
use ratatui::Frame;

use crate::app::{AddFocus, App, Focus, Popup, Stage};

pub fn ui(frame: &mut Frame, app: &App) {
    match app.stage {
        Stage::Pick => draw_pick(frame, app),
        Stage::Ready => draw_ready(frame, app),
    }

    // 弹窗层
    match &app.popup {
        Popup::None => {}
        Popup::Add(state) => draw_add_popup(frame, state),
        Popup::ConfirmDeploy { on_exit } => draw_confirm_deploy_popup(frame, *on_exit),
        Popup::ConfirmDelete {
            word,
            code,
            same_code_count,
            rank,
            ..
        } => draw_confirm_delete_popup(frame, word, code, *same_code_count, *rank),
        Popup::DeployLog { log, .. } => draw_deploy_log_popup(frame, log),
        Popup::SwitchDict(tree) => draw_switch_dict_popup(frame, tree),
        Popup::Message(m) => draw_msg_popup(frame, m),
        Popup::Help => draw_help_popup(frame),
    }
}

fn compute_scroll_window(selected: usize, total: usize, visible_height: usize) -> (usize, usize) {
    if total == 0 || visible_height == 0 {
        return (0, 0);
    }
    if total <= visible_height {
        return (0, total);
    }
    let margin = 2.min(visible_height / 2);
    let start = if selected + margin < visible_height {
        0
    } else {
        (selected + margin + 1)
            .saturating_sub(visible_height)
            .min(total.saturating_sub(visible_height))
    };
    let end = (start + visible_height).min(total);
    (start, end)
}

fn draw_pick(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let [header, main, footer] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Fill(1),
        Constraint::Length(1),
    ])
    .areas(area);

    let title = Line::from(vec![
        Span::styled(
            " 空明码 (kongmingma) 词库管理 TUI ",
            Style::new().bold().cyan(),
        ),
        Span::styled(" - 选择要调整的词库文件", Style::new().dark_gray()),
    ]);
    frame.render_widget(Paragraph::new(title), header);

    // 左右分栏：左侧目录树，右侧文件详情与实时预览
    let [left, right] = Layout::horizontal([
        Constraint::Percentage(58),
        Constraint::Percentage(42),
    ])
    .areas(main);

    // 左侧窗口：平滑滚动目录树
    let visible_height = (left.height.saturating_sub(2)).max(1) as usize;
    let (start, end) = compute_scroll_window(app.dir_tree.selected, app.dir_tree.flat.len(), visible_height);

    let rows: Vec<Row> = (start..end)
        .map(|i| {
            let r = &app.dir_tree.flat[i];
            let is_sel = i == app.dir_tree.selected;
            let indent = "  ".repeat(r.depth);
            let prefix = if r.is_dir { "▸ " } else { "  " };

            let mut spans = vec![Span::raw(format!("{indent}{prefix}"))];
            if r.name.contains("kongming") {
                spans.push(Span::styled(&r.name, Style::new().bold().green()));
            } else {
                spans.push(Span::raw(&r.name));
            }

            if !r.is_dir {
                let mb = r.size as f64 / 1_048_576.0;
                spans.push(Span::styled(
                    format!("   ({mb:.1} MB)"),
                    Style::new().dark_gray(),
                ));
            }

            let style = if is_sel {
                Style::new().reversed().bold().cyan()
            } else {
                Style::new()
            };
            Row::new(vec![Line::from(spans)]).style(style)
        })
        .collect();

    let tree_title = if app.dir_tree.flat.is_empty() {
        " 词库目录树 (空) ".to_string()
    } else {
        format!(
            " 词库目录树 [第 {}/{} 项]（j/k 移动 · l/Enter 打开 · h/Esc 上级 · ^q 退出） ",
            app.dir_tree.selected + 1,
            app.dir_tree.flat.len()
        )
    };
    let table = Table::new(rows, &[Constraint::Fill(1)]).block(
        Block::bordered().title(tree_title),
    );
    frame.render_widget(table, left);

    // 右侧窗口：文件信息与内容预览
    draw_pick_preview(frame, app, right);

    let f = Line::from(Span::styled(app.status.as_str(), Style::new().yellow()));
    frame.render_widget(Paragraph::new(f), footer);
}

fn draw_pick_preview(frame: &mut Frame, app: &App, area: Rect) {
    let block = Block::bordered().title(" 选中项详情与预览 ");
    if app.dir_tree.flat.is_empty() || app.dir_tree.selected >= app.dir_tree.flat.len() {
        let p = Paragraph::new("\n  无选中条目").block(block);
        frame.render_widget(p, area);
        return;
    }

    let r = &app.dir_tree.flat[app.dir_tree.selected];
    let mut lines = Vec::new();

    if r.is_dir {
        lines.push(Line::from(vec![
            Span::styled("类型：", Style::new().bold().dark_gray()),
            Span::styled("目录文件夹", Style::new().bold().yellow()),
        ]));
        lines.push(Line::from(vec![
            Span::styled("名称：", Style::new().bold().dark_gray()),
            Span::styled(&r.name, Style::new().bold().white()),
        ]));
        lines.push(Line::from(vec![
            Span::styled("完整路径：", Style::new().bold().dark_gray()),
            Span::styled(r.path.display().to_string(), Style::new().cyan()),
        ]));
        lines.push(Line::from(""));
        lines.push(Line::from(vec![
            Span::styled("快捷操作：", Style::new().bold().green()),
            Span::raw("按 "),
            Span::styled("l", Style::new().bold().yellow()),
            Span::raw(" 或 "),
            Span::styled("Enter", Style::new().bold().yellow()),
            Span::raw(" 展开/折叠该目录"),
        ]));
        lines.push(Line::from(vec![
            Span::raw("          按 "),
            Span::styled("h", Style::new().bold().yellow()),
            Span::raw(" 返回上级目录"),
        ]));
    } else {
        lines.push(Line::from(vec![
            Span::styled("类型：", Style::new().bold().dark_gray()),
            Span::styled("RIME 词库文件 (.dict.yaml)", Style::new().bold().green()),
        ]));
        lines.push(Line::from(vec![
            Span::styled("名称：", Style::new().bold().dark_gray()),
            Span::styled(&r.name, Style::new().bold().white()),
        ]));
        let mb = r.size as f64 / 1_048_576.0;
        lines.push(Line::from(vec![
            Span::styled("大小：", Style::new().bold().dark_gray()),
            Span::styled(format!("{mb:.2} MB ({} 字节)", r.size), Style::new().yellow()),
        ]));
        lines.push(Line::from(vec![
            Span::styled("完整路径：", Style::new().bold().dark_gray()),
            Span::styled(r.path.display().to_string(), Style::new().cyan()),
        ]));
        lines.push(Line::from(""));
        lines.push(Line::from(vec![
            Span::styled("快捷操作：", Style::new().bold().green()),
            Span::raw("按 "),
            Span::styled("Enter", Style::new().bold().yellow()),
            Span::raw(" 或 "),
            Span::styled("l", Style::new().bold().yellow()),
            Span::raw(" 加载并打开此词库"),
        ]));

        // 读取文件前几行快速预览
        if let Ok(file) = std::fs::File::open(&r.path) {
            use std::io::{BufRead, BufReader};
            let reader = BufReader::new(file);
            lines.push(Line::from(""));
            lines.push(Line::from(Span::styled("--- 文件前段预览 ---", Style::new().bold().dark_gray())));
            let preview_lines = (area.height.saturating_sub(12)).max(3) as usize;
            for (count, line_res) in reader.lines().take(preview_lines).enumerate() {
                if let Ok(l) = line_res {
                    lines.push(Line::from(vec![
                        Span::styled(format!(" {:2} │ ", count + 1), Style::new().dark_gray()),
                        Span::raw(l),
                    ]));
                }
            }
        }
    }

    let p = Paragraph::new(lines).block(block).wrap(Wrap { trim: false });
    frame.render_widget(p, area);
}

fn draw_ready(frame: &mut Frame, app: &App) {
    let area = frame.area();
    let [header, query_bar, main, footer] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(3),
        Constraint::Fill(1),
        Constraint::Length(2),
    ])
    .areas(area);

    // 1. 顶部状态头
    let save_badge = if app.dict.is_saving {
        Span::styled(" [⏳ 正在落盘写盘...] ", Style::new().bold().yellow())
    } else if app.dict.dirty {
        Span::styled(" [✎ 已修改(等待防抖写入)] ", Style::new().bold().cyan())
    } else if let Some(st) = app.dict.last_saved {
        let elapsed = st.elapsed().as_secs();
        if elapsed < 5 {
            Span::styled(" [✔ 实时已保存] ", Style::new().bold().green())
        } else {
            Span::styled(" [✔ 已保存] ", Style::new().green())
        }
    } else {
        Span::styled(" [● 词库就绪] ", Style::new().dark_gray())
    };

    let h = Line::from(vec![
        Span::styled(
            format!(" 词库：{} ", app.dict_name),
            Style::new().bold().cyan(),
        ),
        Span::styled(
            format!("(共 {} 条条目) ", app.dict.len()),
            Style::new().dark_gray(),
        ),
        Span::styled(
            format!(" 模式：[{}] ", app.mode_name()),
            Style::new().bold().magenta(),
        ),
        save_badge,
    ]);
    frame.render_widget(Paragraph::new(h), header);

    // 2. 查询栏
    let cursor = if matches!(app.focus, Focus::Query) {
        "▌"
    } else {
        ""
    };
    let qline = format!(" [{}] {}{}", app.mode_name(), app.query, cursor);
    let qstyle = if matches!(app.focus, Focus::Query) {
        Style::new().reversed()
    } else {
        Style::new()
    };
    frame.render_widget(
        Paragraph::new(Line::from(qline)).block(
            Block::bordered()
                .title(" 检索（/ 聚焦 · Tab 切换编码/拼音/字词 · 回车检索 · Esc 结果区） ")
                .style(qstyle),
        ),
        query_bar,
    );

    // 3. 主双栏区域
    let [left, right] =
        Layout::horizontal([Constraint::Percentage(58), Constraint::Percentage(42)]).areas(main);
    draw_results_table(frame, app, left);
    draw_candidate_panel(frame, app, right);

    // 4. 底部状态与快捷键提示（Vim-like 风格）
    let shortcuts = Line::from(vec![
        Span::styled("Normal: ", Style::new().bold().green()),
        Span::styled("j/k ", Style::new().bold().yellow()),
        Span::raw("移动  "),
        Span::styled("J/K ", Style::new().bold().yellow()),
        Span::raw("候选调序  "),
        Span::styled("H/L ", Style::new().bold().yellow()),
        Span::raw("置顶/底  "),
        Span::styled("gg/G ", Style::new().bold().yellow()),
        Span::raw("首/尾  "),
        Span::styled("^d/^u ", Style::new().bold().yellow()),
        Span::raw("翻页  "),
        Span::styled("/,i ", Style::new().bold().yellow()),
        Span::raw("检索  "),
        Span::styled("a ", Style::new().bold().yellow()),
        Span::raw("添加  "),
        Span::styled("x ", Style::new().bold().yellow()),
        Span::raw("删除  "),
        Span::styled("w ", Style::new().bold().yellow()),
        Span::raw("保存  "),
        Span::styled("o ", Style::new().bold().yellow()),
        Span::raw("换库  "),
        Span::styled("d ", Style::new().bold().yellow()),
        Span::raw("部署  "),
        Span::styled("^q ", Style::new().bold().yellow()),
        Span::raw("退出"),
    ]);
    let status_line = Line::from(vec![
        Span::styled("状态: ", Style::new().bold().dark_gray()),
        Span::styled(&app.status, Style::new().yellow()),
    ]);
    frame.render_widget(Paragraph::new(vec![shortcuts, status_line]), footer);
}

fn draw_results_table(frame: &mut Frame, app: &App, area: Rect) {
    let visible_height = (area.height.saturating_sub(4)).max(1) as usize; // header row + borders
    let (start, end) = compute_scroll_window(app.selected, app.results.len(), visible_height);

    let rows: Vec<Row> = (start..end)
        .map(|i| {
            let idx = app.results[i];
            let is_sel = i == app.selected;

            let word = app.dict.word(idx).to_string();
            let code = app.dict.code(idx).to_string();
            let rank_info = match app.dict.candidate_rank(idx) {
                Some((rank, total)) => {
                    if total > 1 {
                        format!("第 {rank}/{total} 候选")
                    } else {
                        "独占".to_string()
                    }
                }
                None => "-".to_string(),
            };

            let row_style = if is_sel {
                Style::new().reversed().bold().cyan()
            } else {
                Style::new()
            };

            Row::new(vec![word, code, rank_info]).style(row_style)
        })
        .collect();

    let title = if app.results.is_empty() {
        " 检索结果 (共 0 条) ".to_string()
    } else {
        format!(" 检索结果 [第 {}/{} 条] ", app.selected + 1, app.results.len())
    };
    let table = Table::new(
        rows,
        &[
            Constraint::Percentage(45),
            Constraint::Percentage(30),
            Constraint::Percentage(25),
        ],
    )
    .header(
        Row::new(vec!["字词", "编码", "重码位次"])
            .style(Style::new().bold().underlined()),
    )
    .block(Block::bordered().title(title));

    frame.render_widget(table, area);
}

fn draw_candidate_panel(frame: &mut Frame, app: &App, area: Rect) {
    let block = Block::bordered().title(" 同码候选项与 Rime 字顺 ");

    if app.results.is_empty() || app.selected >= app.results.len() {
        let p = Paragraph::new("\n  暂无选中条目。按 / 检索或 a 添加新字词。")
            .style(Style::new().dark_gray())
            .block(block);
        frame.render_widget(p, area);
        return;
    }

    let curr_entry = app.results[app.selected];
    let curr_code = app.dict.code(curr_entry);
    let same_entries = app.dict.get_same_code_entries(curr_code);

    let mut lines = Vec::new();
    lines.push(Line::from(vec![
        Span::raw(" 当前编码："),
        Span::styled(curr_code, Style::new().bold().green()),
        Span::raw("  （重码候选数："),
        Span::styled(format!("{}", same_entries.len()), Style::new().bold().yellow()),
        Span::raw("）"),
    ]));
    lines.push(Line::from(vec![
        Span::styled(" [J/K] ", Style::new().bold().cyan()),
        Span::raw("顺位下移/上移  "),
        Span::styled(" [H/L] ", Style::new().bold().cyan()),
        Span::raw("置顶首选/置底"),
    ]));
    lines.push(Line::from(""));

    for (pos, &entry_idx) in same_entries.iter().enumerate() {
        let w = app.dict.word(entry_idx);
        let rank = pos + 1;
        let is_current = entry_idx == curr_entry;

        let num_str = format!("  {rank:2}. ");
        if is_current {
            lines.push(Line::from(vec![
                Span::styled(num_str, Style::new().bold().cyan()),
                Span::styled(w, Style::new().bold().reversed().yellow()),
                Span::styled("  ◀ 当前选中", Style::new().bold().cyan()),
            ]));
        } else {
            lines.push(Line::from(vec![
                Span::styled(num_str, Style::new().dark_gray()),
                Span::styled(w, Style::new()),
            ]));
        }
    }

    let p = Paragraph::new(lines).block(block).wrap(Wrap { trim: false });
    frame.render_widget(p, area);
}

fn draw_add_popup(frame: &mut Frame, state: &crate::app::AddState) {
    let area = centered_rect(76, 20, frame.area());
    frame.render_widget(Clear, area);

    let block = Block::bordered()
        .title(" 添加字词并推导空明码 ")
        .border_style(Style::new().bold().cyan());
    frame.render_widget(block, area);

    let inner = Rect {
        x: area.x + 2,
        y: area.y + 1,
        width: area.width.saturating_sub(4),
        height: area.height.saturating_sub(2),
    };

    let [w_sec, char_sec, deduce_sec, c_sec, check_sec, foot_sec] = Layout::vertical([
        Constraint::Length(3),
        Constraint::Length(2),
        Constraint::Length(4),
        Constraint::Length(3),
        Constraint::Length(2),
        Constraint::Length(1),
    ])
    .areas(inner);

    // 1. 字词输入框
    let w_style = if state.focus == AddFocus::Word {
        Style::new().bold().cyan()
    } else {
        Style::new()
    };
    let w_cursor = if state.focus == AddFocus::Word { "▌" } else { "" };
    frame.render_widget(
        Paragraph::new(format!(" {}{}", state.word, w_cursor)).block(
            Block::bordered()
                .title(" 1. 输入待添加字词（Tab 切换） ")
                .border_style(w_style),
        ),
        w_sec,
    );

    // 2. 单字码表拆解展示
    let mut char_spans = vec![Span::raw("单字编码参考：")];
    if state.char_breakdown.is_empty() {
        char_spans.push(Span::styled("（请输入字词）", Style::new().dark_gray()));
    } else {
        for (ch, list) in &state.char_breakdown {
            char_spans.push(Span::styled(format!(" [{ch}: "), Style::new().bold()));
            if list.is_empty() {
                char_spans.push(Span::styled("缺", Style::new().red()));
            } else {
                char_spans.push(Span::styled(list.join(","), Style::new().green()));
            }
            char_spans.push(Span::styled("] ", Style::new().bold()));
        }
    }
    frame.render_widget(Paragraph::new(Line::from(char_spans)), char_sec);

    // 3. 推导推荐编码
    let mut deduce_lines = Vec::new();
    let d_style = if state.focus == AddFocus::Deductions {
        Style::new().bold().yellow()
    } else {
        Style::new()
    };

    if state.deduced_codes.is_empty() {
        deduce_lines.push(Line::from("  （无自动推导候选，可在下方直接手输编码）"));
    } else {
        let mut row_spans = vec![Span::raw("  推荐候选：")];
        for (idx, code) in state.deduced_codes.iter().enumerate() {
            let is_sel = idx == state.selected_deduced;
            if is_sel {
                row_spans.push(Span::styled(
                    format!(" [{code}] "),
                    Style::new().bold().reversed().yellow(),
                ));
            } else {
                row_spans.push(Span::styled(format!("  {code}  "), Style::new().cyan()));
            }
        }
        deduce_lines.push(Line::from(row_spans));
        deduce_lines.push(Line::from(Span::styled(
            "  (↑/↓ 键选候选，回车代入下方)",
            Style::new().dark_gray(),
        )));
    }
    frame.render_widget(
        Paragraph::new(deduce_lines).block(
            Block::bordered()
                .title(" 2. 空明码自动推导候选 ")
                .border_style(d_style),
        ),
        deduce_sec,
    );

    // 4. 最终确认编码输入框
    let c_style = if state.focus == AddFocus::Code {
        Style::new().bold().cyan()
    } else {
        Style::new()
    };
    let c_cursor = if state.focus == AddFocus::Code { "▌" } else { "" };
    frame.render_widget(
        Paragraph::new(format!(" {}{}", state.code, c_cursor)).block(
            Block::bordered()
                .title(" 3. 最终词条编码（可自由修改，回车添加） ")
                .border_style(c_style),
        ),
        c_sec,
    );

    // 5. 重码与冲突实时提示
    let check_msg = if state.is_exact_duplicate {
        Line::from(Span::styled(
            "✖ 词库中已存在完全相同的「字词+编码」！无法重复添加。",
            Style::new().bold().red(),
        ))
    } else if !state.same_codes.is_empty() {
        Line::from(vec![
            Span::styled("⚠ 存在重码词：", Style::new().bold().yellow()),
            Span::styled(state.same_codes.join("、"), Style::new().yellow()),
            Span::styled(
                format!(" （新增后将排在第 {} 候选）", state.same_codes.len() + 1),
                Style::new().dark_gray(),
            ),
        ])
    } else if !state.code.is_empty() {
        Line::from(Span::styled(
            "✔ 编码独占无重码，将作为第 1 首选项录入。",
            Style::new().bold().green(),
        ))
    } else {
        Line::from("")
    };
    frame.render_widget(Paragraph::new(check_msg), check_sec);

    // 6. 底部按键提示
    let foot = Line::from(Span::styled(
        " [Tab] 切换输入区  [Enter] 确认添加  [Esc] 取消并返回 ",
        Style::new().dark_gray(),
    ));
    frame.render_widget(Paragraph::new(foot), foot_sec);
}

fn draw_confirm_deploy_popup(frame: &mut Frame, on_exit: bool) {
    let area = centered_rect(64, 10, frame.area());
    frame.render_widget(Clear, area);

    let title = if on_exit {
        " 退出与重新部署确认 "
    } else {
        " 重新部署确认 "
    };
    let block = Block::bordered()
        .title(title)
        .border_style(Style::new().bold().yellow());
    frame.render_widget(block, area);

    let inner = Rect {
        x: area.x + 2,
        y: area.y + 1,
        width: area.width.saturating_sub(4),
        height: area.height.saturating_sub(2),
    };

    let text = if on_exit {
        vec![
            Line::from("检测到词库有修改。是否同步并重新部署 fcitx5-rime？"),
            Line::from(""),
            Line::from(vec![
                Span::styled("  [Y / Enter] ", Style::new().bold().green()),
                Span::raw("同步词库、重新部署并退出"),
            ]),
            Line::from(vec![
                Span::styled("  [N]         ", Style::new().bold().yellow()),
                Span::raw("仅保存修改，直接退出不部署"),
            ]),
            Line::from(vec![
                Span::styled("  [Esc]       ", Style::new().bold().dark_gray()),
                Span::raw("取消退出，返回程序"),
            ]),
        ]
    } else {
        vec![
            Line::from("是否立即同步当前词库并重新部署 fcitx5-rime？"),
            Line::from(""),
            Line::from(vec![
                Span::styled("  [Y / Enter] ", Style::new().bold().green()),
                Span::raw("立即部署"),
            ]),
            Line::from(vec![
                Span::styled("  [Esc / N]   ", Style::new().bold().dark_gray()),
                Span::raw("取消"),
            ]),
        ]
    };

    frame.render_widget(Paragraph::new(text), inner);
}

fn draw_confirm_delete_popup(
    frame: &mut Frame,
    word: &str,
    code: &str,
    same_code_count: usize,
    rank: usize,
) {
    let area = centered_rect(62, 10, frame.area());
    frame.render_widget(Clear, area);

    let block = Block::bordered()
        .title(" 删除条目确认 ")
        .border_style(Style::new().bold().red());
    frame.render_widget(block, area);

    let inner = Rect {
        x: area.x + 2,
        y: area.y + 1,
        width: area.width.saturating_sub(4),
        height: area.height.saturating_sub(2),
    };

    let impact_line = if same_code_count > 1 {
        Line::from(vec![
            Span::styled("  同码影响：", Style::new().dark_gray()),
            Span::styled(
                format!(
                    "当前排第 [{rank}/{same_code_count}] 位（删除后剩余 {} 项，后续候选顺位自动前移）",
                    same_code_count - 1
                ),
                Style::new().yellow(),
            ),
        ])
    } else {
        Line::from(vec![
            Span::styled("  同码影响：", Style::new().dark_gray()),
            Span::styled("该编码下唯一条目（删除后该编码将无候选）", Style::new().dark_gray()),
        ])
    };

    let text = vec![
        Line::from(vec![
            Span::styled("确认删除条目：", Style::new().bold()),
            Span::styled(format!(" {word} "), Style::new().bold().yellow().reversed()),
            Span::raw("    编码："),
            Span::styled(format!(" {code} "), Style::new().bold().cyan()),
        ]),
        Line::from(""),
        impact_line,
        Line::from(""),
        Line::from(vec![
            Span::styled("  [Y / Enter] ", Style::new().bold().red()),
            Span::raw("确认删除      "),
            Span::styled("  [N / Esc / q] ", Style::new().bold().dark_gray()),
            Span::raw("取消返回"),
        ]),
    ];

    frame.render_widget(Paragraph::new(text), inner);
}

fn draw_deploy_log_popup(frame: &mut Frame, log: &str) {
    let area = centered_rect(76, 18, frame.area());
    frame.render_widget(Clear, area);

    let block = Block::bordered()
        .title(" fcitx5-rime 部署与重载输出 ")
        .border_style(Style::new().bold().cyan());
    frame.render_widget(block, area);

    let inner = Rect {
        x: area.x + 2,
        y: area.y + 1,
        width: area.width.saturating_sub(4),
        height: area.height.saturating_sub(2),
    };

    let p = Paragraph::new(log)
        .wrap(Wrap { trim: false })
        .style(Style::new().white());
    frame.render_widget(p, inner);
}

fn draw_switch_dict_popup(frame: &mut Frame, tree: &crate::dirtree::DirTree) {
    let area = centered_rect(72, 18, frame.area());
    frame.render_widget(Clear, area);

    let block = Block::bordered()
        .title(" 切换词库 (↑↓ 移动 · Enter 打开 · Esc 取消) ")
        .border_style(Style::new().bold().magenta());
    frame.render_widget(block, area);

    let inner = Rect {
        x: area.x + 1,
        y: area.y + 1,
        width: area.width.saturating_sub(2),
        height: area.height.saturating_sub(2),
    };

    let visible_height = inner.height.max(1) as usize;
    let (start, end) = compute_scroll_window(tree.selected, tree.flat.len(), visible_height);

    let rows: Vec<Row> = (start..end)
        .map(|i| {
            let r = &tree.flat[i];
            let is_sel = i == tree.selected;
            let indent = "  ".repeat(r.depth);
            let prefix = if r.is_dir { "▸ " } else { "  " };

            let mut spans = vec![Span::raw(format!("{indent}{prefix}"))];
            if r.name.contains("kongming") {
                spans.push(Span::styled(&r.name, Style::new().bold().green()));
            } else {
                spans.push(Span::raw(&r.name));
            }

            if !r.is_dir {
                let mb = r.size as f64 / 1_048_576.0;
                spans.push(Span::styled(
                    format!("   ({mb:.1} MB)"),
                    Style::new().dark_gray(),
                ));
            }

            let style = if is_sel {
                Style::new().reversed().bold().cyan()
            } else {
                Style::new()
            };
            Row::new(vec![Line::from(spans)]).style(style)
        })
        .collect();

    let table = Table::new(rows, &[Constraint::Fill(1)]);
    frame.render_widget(table, inner);
}

fn draw_msg_popup(frame: &mut Frame, msg: &str) {
    let area = centered_rect(60, 8, frame.area());
    frame.render_widget(Clear, area);

    let block = Block::bordered()
        .title(" 提示 ")
        .border_style(Style::new().bold().yellow());
    frame.render_widget(block, area);

    let inner = Rect {
        x: area.x + 2,
        y: area.y + 2,
        width: area.width.saturating_sub(4),
        height: area.height.saturating_sub(4),
    };

    let p = Paragraph::new(msg).wrap(Wrap { trim: false });
    frame.render_widget(p, inner);
}

fn draw_help_popup(frame: &mut Frame) {
    let area = centered_rect(70, 20, frame.area());
    frame.render_widget(Clear, area);

    let block = Block::bordered()
        .title(" 帮助与按键指南 ")
        .border_style(Style::new().bold().cyan());
    frame.render_widget(block, area);

    let inner = Rect {
        x: area.x + 2,
        y: area.y + 1,
        width: area.width.saturating_sub(4),
        height: area.height.saturating_sub(2),
    };

    let text = vec![
        Line::from(Span::styled("【Vim 风格快捷键指南】", Style::new().bold().yellow())),
        Line::from("  j / k              向下 / 向上移动光标"),
        Line::from("  gg / G             跳转至结果首行 / 末行"),
        Line::from("  Ctrl+d / Ctrl+u    向下 / 向上翻半页 (10 行)"),
        Line::from("  Ctrl+f / Ctrl+b    向下 / 向上翻整页 (25 行)"),
        Line::from("  n / N              跳至下一个 / 上一个条目"),
        Line::from("  / 或 i             进入检索模式（检索框输入；Esc 返回 Normal）"),
        Line::from("  Tab                循环切换检索模式（编码 / 拼音 / 字词）"),
        Line::from("  a                  添加字词（支持单字码参考与自动推导）"),
        Line::from("  x 或 Delete        删除当前选中的条目（弹窗确认）"),
        Line::from("  K (Shift+K)        同码候选项向上微调位次（提高候选优先级）"),
        Line::from("  J (Shift+J)        同码候选项向下微调位次"),
        Line::from("  H (Shift+H)        同码候选项直接置顶为第 1 首选"),
        Line::from("  L (Shift+L)        同码候选项直接置底为末选"),
        Line::from("  w 或 Ctrl+s        立即落盘保存当前修改（平时自动 300ms 异步防抖写盘）"),
        Line::from("  o                  唤出词库切换抽屉，快速切换其它 .dict.yaml"),
        Line::from("  d 或 Ctrl+r        重新部署并同步词库至 fcitx5-rime"),
        Line::from("  Ctrl+q (或 Ctrl+c) 退出程序（检测到修改时弹出部署确认）"),
        Line::from(""),
        Line::from(Span::styled("【实时写盘与备份】", Style::new().bold().yellow())),
        Line::from("  任何调序或新增均在后台原子写入，自动生成 .bak 安全备份。"),
    ];

    frame.render_widget(Paragraph::new(text), inner);
}

fn centered_rect(percent_x: u16, height_lines: u16, r: Rect) -> Rect {
    let popup_layout = Layout::vertical([
        Constraint::Fill(1),
        Constraint::Length(height_lines),
        Constraint::Fill(1),
    ])
    .split(r);

    Layout::horizontal([
        Constraint::Percentage((100 - percent_x) / 2),
        Constraint::Percentage(percent_x),
        Constraint::Percentage((100 - percent_x) / 2),
    ])
    .split(popup_layout[1])[1]
}
