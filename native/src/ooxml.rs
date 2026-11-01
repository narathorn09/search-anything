//! Office Open XML packages: zip parts and relationships.

use std::fs::File;
use std::io::{BufReader, Read};

use crate::Result;

pub const W: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
pub const A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
pub const P: &str = "http://schemas.openxmlformats.org/presentationml/2006/main";
pub const R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

const MAX_PART_BYTES: u64 = 256 * 1024 * 1024; // refuse absurd (zip-bomb) parts

pub struct Package {
    zip: zip::ZipArchive<BufReader<File>>,
}

pub struct Rel {
    pub id: String,
    pub kind: String,
    pub target: String, // resolved part name, without a leading "/"
    pub external: bool,
}

impl Package {
    pub fn open(path: &str) -> Result<Self> {
        let zip = zip::ZipArchive::new(BufReader::new(File::open(path)?))?;
        Ok(Package { zip })
    }

    pub fn has(&mut self, name: &str) -> bool {
        self.zip.by_name(name).is_ok()
    }

    pub fn read(&mut self, name: &str) -> Result<String> {
        let mut entry = self.zip.by_name(name)?;
        if entry.size() > MAX_PART_BYTES {
            return Err(crate::Error(format!("{name} is too large")));
        }
        let mut bytes = Vec::with_capacity(entry.size() as usize);
        entry.read_to_end(&mut bytes)?;
        decode(bytes)
    }

    /// Relationships of a part ("" = the package itself).
    pub fn rels(&mut self, part: &str) -> Result<Vec<Rel>> {
        let (dir, file) = match part.rfind('/') {
            Some(i) => (&part[..i], &part[i + 1..]),
            None => ("", part),
        };
        let rels_name = if dir.is_empty() { format!("_rels/{file}.rels") } else { format!("{dir}/_rels/{file}.rels") };
        if !self.has(&rels_name) {
            return Ok(Vec::new());
        }
        let xml = self.read(&rels_name)?;
        let doc = roxmltree::Document::parse(&xml)?;
        let mut out = Vec::new();
        for node in doc.root_element().children().filter(|n| n.has_tag_name("Relationship")) {
            let external = node.attribute("TargetMode") == Some("External");
            let target = node.attribute("Target").unwrap_or("");
            out.push(Rel {
                id: node.attribute("Id").unwrap_or("").to_string(),
                kind: node.attribute("Type").unwrap_or("").to_string(),
                target: if external { target.to_string() } else { resolve(dir, target) },
                external,
            });
        }
        Ok(out)
    }

    /// The main part (officeDocument relationship), e.g. "word/document.xml".
    pub fn main_part(&mut self, fallback: &str) -> Result<String> {
        for rel in self.rels("")? {
            if rel.kind.ends_with("/officeDocument") && !rel.external {
                return Ok(rel.target);
            }
        }
        Ok(fallback.to_string())
    }
}

/// XML parts are UTF-8 (or UTF-16 with a BOM).
fn decode(bytes: Vec<u8>) -> Result<String> {
    if bytes.starts_with(&[0xFF, 0xFE]) || bytes.starts_with(&[0xFE, 0xFF]) {
        let le = bytes[0] == 0xFF;
        let units: Vec<u16> = bytes[2..]
            .chunks_exact(2)
            .map(|c| if le { u16::from_le_bytes([c[0], c[1]]) } else { u16::from_be_bytes([c[0], c[1]]) })
            .collect();
        return Ok(String::from_utf16_lossy(&units));
    }
    let start = if bytes.starts_with(&[0xEF, 0xBB, 0xBF]) { 3 } else { 0 };
    match String::from_utf8(bytes) {
        Ok(s) => Ok(s[start..].to_string()),
        Err(e) => Ok(String::from_utf8_lossy(&e.into_bytes()[start..]).into_owned()),
    }
}

/// Resolve a relationship target against the source part's folder.
pub fn resolve(dir: &str, target: &str) -> String {
    let joined = if let Some(abs) = target.strip_prefix('/') { abs.to_string() } else if dir.is_empty() {
        target.to_string()
    } else {
        format!("{dir}/{target}")
    };
    let mut parts: Vec<&str> = Vec::new();
    for seg in joined.split('/') {
        match seg {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            s => parts.push(s),
        }
    }
    parts.join("/")
}

#[cfg(test)]
mod tests {
    use super::resolve;

    #[test]
    fn resolves_targets() {
        assert_eq!(resolve("ppt/slides", "../notesSlides/notesSlide1.xml"), "ppt/notesSlides/notesSlide1.xml");
        assert_eq!(resolve("ppt", "slides/slide1.xml"), "ppt/slides/slide1.xml");
        assert_eq!(resolve("", "word/document.xml"), "word/document.xml");
        assert_eq!(resolve("word", "/word/document.xml"), "word/document.xml");
    }
}
