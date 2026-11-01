//! .docx text, matching python-docx as used by `extractors._docx`:
//! every body paragraph (`document.paragraphs`), then every body table row
//! (`"\t".join(cell.text for cell in row.cells)`), including python-docx's
//! handling of horizontally (gridSpan) and vertically (vMerge) merged cells.

use roxmltree::{Document, Node};

use crate::ooxml::{Package, W};
use crate::{Collector, Result};

fn is_w(node: &Node, name: &str) -> bool {
    node.is_element() && node.tag_name().name() == name && node.tag_name().namespace() == Some(W)
}

fn w_children<'a, 'i>(node: Node<'a, 'i>, name: &'static str) -> impl Iterator<Item = Node<'a, 'i>> {
    node.children().filter(move |c| is_w(c, name))
}

fn w_attr<'a>(node: &Node<'a, '_>, name: &str) -> Option<&'a str> {
    node.attribute((W, name))
}

fn all_text(node: &Node) -> String {
    node.children().filter(|c| c.is_text()).filter_map(|c| c.text()).collect()
}

/// `CT_R.text`: w:br | w:cr | w:noBreakHyphen | w:ptab | w:t | w:tab, in order.
fn run_text(r: Node, out: &mut String) {
    for c in r.children().filter(|c| c.is_element() && c.tag_name().namespace() == Some(W)) {
        match c.tag_name().name() {
            "t" => out.push_str(&all_text(&c)),
            "tab" | "ptab" => out.push('\t'),
            "cr" => out.push('\n'),
            "br" => {
                if w_attr(&c, "type").unwrap_or("textWrapping") == "textWrapping" {
                    out.push('\n')
                }
            }
            "noBreakHyphen" => out.push('-'),
            _ => {}
        }
    }
}

/// `CT_P.text`: direct w:r and w:hyperlink children (a hyperlink's direct w:r).
pub fn paragraph_text(p: Node) -> String {
    let mut out = String::new();
    for c in p.children() {
        if is_w(&c, "r") {
            run_text(c, &mut out);
        } else if is_w(&c, "hyperlink") {
            for r in w_children(c, "r") {
                run_text(r, &mut out);
            }
        }
    }
    out
}

fn cell_text(tc: Node) -> String {
    w_children(tc, "p").map(paragraph_text).collect::<Vec<_>>().join("\n")
}

fn tc_pr_val<'a>(tc: &Node<'a, '_>, name: &str) -> Option<Option<&'a str>> {
    let pr = w_children(*tc, "tcPr").next()?;
    pr.children().find(|c| is_w(c, name)).map(|e| w_attr(&e, "val"))
}

fn grid_span(tc: &Node) -> usize {
    tc_pr_val(tc, "gridSpan").flatten().and_then(|v| v.parse::<usize>().ok()).unwrap_or(1).max(1)
}

fn v_merge_continue(tc: &Node) -> bool {
    // <w:vMerge/> without a value means "continue".
    matches!(tc_pr_val(tc, "vMerge"), Some(None) | Some(Some("continue")))
}

fn grid_before(tr: &Node) -> usize {
    w_children(*tr, "trPr")
        .next()
        .and_then(|pr| pr.children().find(|c| is_w(c, "gridBefore")))
        .and_then(|e| w_attr(&e, "val").and_then(|v| v.parse::<usize>().ok()))
        .unwrap_or(0)
}

/// The w:tc that starts at `offset` in a row (python-docx `tc_at_grid_offset`).
fn tc_at_offset<'a, 'i>(tr: Node<'a, 'i>, offset: usize) -> Option<Node<'a, 'i>> {
    let mut pos = grid_before(&tr);
    for tc in w_children(tr, "tc") {
        if pos == offset {
            return Some(tc);
        }
        pos += grid_span(&tc);
        if pos > offset {
            return None;
        }
    }
    None
}

/// Text of the cell a vertically merged tc continues (recursively upwards).
fn merged_origin_text(rows: &[Node], row: usize, offset: usize) -> Option<String> {
    let mut r = row;
    while r > 0 {
        r -= 1;
        let tc = tc_at_offset(rows[r], offset)?;
        if !v_merge_continue(&tc) {
            return Some(cell_text(tc));
        }
    }
    None
}

fn table_rows(tbl: Node, out: &mut Collector) -> Result<()> {
    let rows: Vec<Node> = w_children(tbl, "tr").collect();
    for (i, tr) in rows.iter().enumerate() {
        let mut cells: Vec<String> = Vec::new();
        let mut offset = grid_before(tr);
        for tc in w_children(*tr, "tc") {
            let span = grid_span(&tc);
            if v_merge_continue(&tc) {
                // python-docx yields the origin cell's cells (its own span).
                let text = merged_origin_text(&rows, i, offset)
                    .ok_or_else(|| crate::Error("no cell above a merged cell".into()))?;
                for _ in 0..span {
                    cells.push(text.clone());
                }
            } else {
                let text = cell_text(tc);
                for _ in 0..span {
                    cells.push(text.clone());
                }
            }
            offset += span;
        }
        out.add(cells.join("\t"));
    }
    Ok(())
}

pub fn extract(path: &str, cap: usize) -> Result<String> {
    let mut pkg = Package::open(path)?;
    let main = pkg.main_part("word/document.xml")?;
    let xml = pkg.read(&main)?;
    from_xml(&xml, cap)
}

pub fn from_xml(xml: &str, cap: usize) -> Result<String> {
    let doc = Document::parse(xml)?;
    let body = doc
        .root_element()
        .children()
        .find(|c| is_w(c, "body"))
        .ok_or_else(|| crate::Error("no w:body".into()))?;
    let mut out = Collector::new(cap);
    for p in w_children(body, "p") {
        out.add(paragraph_text(p));
    }
    for tbl in w_children(body, "tbl") {
        table_rows(tbl, &mut out)?;
    }
    Ok(out.text())
}
