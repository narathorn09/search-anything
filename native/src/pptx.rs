//! .pptx text, matching python-pptx as used by `extractors._pptx`: per slide
//! "# สไลด์ N", the text of each top-level shape with a text frame, each table
//! row ("\t"-joined cells), then the notes placeholder text.

use roxmltree::{Document, Node};

use crate::ooxml::{Package, A, P, R};
use crate::{Collector, Result};

const TABLE_URI: &str = "http://schemas.openxmlformats.org/drawingml/2006/table";

fn is(node: &Node, ns: &str, name: &str) -> bool {
    node.is_element() && node.tag_name().name() == name && node.tag_name().namespace() == Some(ns)
}

fn child<'a, 'i>(node: Node<'a, 'i>, ns: &'static str, name: &'static str) -> Option<Node<'a, 'i>> {
    node.children().find(|c| is(c, ns, name))
}

fn children<'a, 'i>(node: Node<'a, 'i>, ns: &'static str, name: &'static str) -> impl Iterator<Item = Node<'a, 'i>> {
    node.children().filter(move |c| is(c, ns, name))
}

fn all_text(node: &Node) -> String {
    node.children().filter(|c| c.is_text()).filter_map(|c| c.text()).collect()
}

/// `_Paragraph.text`: a:r and a:fld text, "\v" for each a:br.
fn paragraph_text(p: Node) -> String {
    let mut out = String::new();
    for c in p.children() {
        if is(&c, A, "r") || is(&c, A, "fld") {
            if let Some(t) = child(c, A, "t") {
                out.push_str(&all_text(&t));
            }
        } else if is(&c, A, "br") {
            out.push('\u{b}');
        }
    }
    out
}

/// `TextFrame.text`: paragraphs joined with "\n" ("" without a text body).
fn frame_text(tx_body: Option<Node>) -> String {
    match tx_body {
        Some(body) => children(body, A, "p").map(paragraph_text).collect::<Vec<_>>().join("\n"),
        None => String::new(),
    }
}

fn shape_elements<'a, 'i>(sp_tree: Node<'a, 'i>) -> impl Iterator<Item = Node<'a, 'i>> {
    sp_tree.children().filter(|c| {
        c.is_element()
            && c.tag_name().namespace() == Some(P)
            && matches!(c.tag_name().name(), "sp" | "grpSp" | "graphicFrame" | "cxnSp" | "pic" | "contentPart")
    })
}

fn sp_tree<'a, 'i>(doc: &'a Document<'i>) -> Option<Node<'a, 'i>> {
    let csld = child(doc.root_element(), P, "cSld")?;
    child(csld, P, "spTree")
}

fn slide_text(xml: &str, n: usize, out: &mut Collector) -> Result<()> {
    out.add(format!("# สไลด์ {n}"));
    let doc = Document::parse(xml)?;
    let Some(tree) = sp_tree(&doc) else { return Ok(()) };
    for shape in shape_elements(tree) {
        if is(&shape, P, "sp") {
            out.add(frame_text(child(shape, P, "txBody")));
        } else if is(&shape, P, "graphicFrame") {
            let data = child(shape, A, "graphic").and_then(|g| child(g, A, "graphicData"));
            if let Some(data) = data.filter(|d| d.attribute("uri") == Some(TABLE_URI)) {
                if let Some(tbl) = child(data, A, "tbl") {
                    for tr in children(tbl, A, "tr") {
                        let cells: Vec<String> = children(tr, A, "tc").map(|tc| frame_text(child(tc, A, "txBody"))).collect();
                        out.add(cells.join("\t"));
                    }
                }
            }
        }
    }
    Ok(())
}

/// Text of the notes placeholder (`ph type="body"`), like `notes_text_frame.text`.
fn notes_text(xml: &str) -> Result<String> {
    let doc = Document::parse(xml)?;
    if let Some(tree) = sp_tree(&doc) {
        for shape in shape_elements(tree) {
            let nv_pr = shape
                .children()
                .find(|c| c.is_element() && c.tag_name().namespace() == Some(P) && c.tag_name().name().starts_with("nv"))
                .and_then(|nv| child(nv, P, "nvPr"));
            let Some(ph) = nv_pr.and_then(|nv| child(nv, P, "ph")) else { continue };
            if ph.attribute("type").unwrap_or("obj") == "body" {
                return Ok(frame_text(child(shape, P, "txBody")));
            }
        }
    }
    Err(crate::Error("notes slide has no notes placeholder".into()))
}

pub fn extract(path: &str, cap: usize) -> Result<String> {
    let mut pkg = Package::open(path)?;
    let main = pkg.main_part("ppt/presentation.xml")?;
    let pres_xml = pkg.read(&main)?;
    let rels = pkg.rels(&main)?;
    let pres = Document::parse(&pres_xml)?;
    let ids: Vec<String> = child(pres.root_element(), P, "sldIdLst")
        .map(|l| children(l, P, "sldId").filter_map(|s| s.attribute((R, "id")).map(str::to_string)).collect())
        .unwrap_or_default();
    let mut out = Collector::new(cap);
    for (i, id) in ids.iter().enumerate() {
        let Some(rel) = rels.iter().find(|r| &r.id == id && !r.external) else { continue };
        let slide_xml = pkg.read(&rel.target)?;
        slide_text(&slide_xml, i + 1, &mut out)?;
        let notes = pkg.rels(&rel.target)?.into_iter().find(|r| r.kind.ends_with("/notesSlide") && !r.external);
        if let Some(notes) = notes {
            let xml = pkg.read(&notes.target)?;
            out.add(notes_text(&xml)?);
        }
    }
    Ok(out.text())
}
