//! Old binary Office formats (97-2003): Word .doc and PowerPoint .ppt.
//! Same rules, same output as `cahon/legacy.py` (see there).
//! (.xls is read with calamine in xlsx.rs.)

use std::fs::File;
use std::io::Read;

use crate::Result;

const MAX_STREAM_BYTES: u64 = 256 * 1024 * 1024;

fn read_stream(cf: &mut cfb::CompoundFile<File>, name: &str) -> Result<Vec<u8>> {
    let path = format!("/{name}");
    if !cf.is_stream(&path) {
        return Err(crate::Error(format!("no {name} stream")));
    }
    let mut stream = cf.open_stream(&path)?;
    if stream.len() > MAX_STREAM_BYTES {
        return Err(crate::Error(format!("{name} is too large")));
    }
    let mut buf = Vec::with_capacity(stream.len() as usize);
    stream.read_to_end(&mut buf)?;
    Ok(buf)
}

fn open(path: &str) -> Result<cfb::CompoundFile<File>> {
    cfb::open(path).map_err(|e| crate::Error(format!("not an OLE2 (97-2003) file: {e}")))
}

fn u16_at(b: &[u8], i: usize) -> Result<u16> {
    b.get(i..i + 2).map(|s| u16::from_le_bytes([s[0], s[1]])).ok_or_else(|| crate::Error("truncated file".into()))
}

fn u32_at(b: &[u8], i: usize) -> Result<u32> {
    b.get(i..i + 4)
        .map(|s| u32::from_le_bytes([s[0], s[1], s[2], s[3]]))
        .ok_or_else(|| crate::Error("truncated file".into()))
}

/// Python's bytes.decode("utf-16-le", errors="replace").
fn utf16le(b: &[u8]) -> String {
    let units: Vec<u16> = b.chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
    let mut s = String::from_utf16_lossy(&units);
    if b.len() % 2 == 1 {
        s.push('\u{FFFD}');
    }
    s
}

/// Python's bytes.decode("cp1252", errors="replace").
fn cp1252(b: &[u8]) -> String {
    const HIGH: [u32; 32] = [
        0x20AC, 0xFFFD, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0xFFFD,
        0x017D, 0xFFFD, 0xFFFD, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A,
        0x0153, 0xFFFD, 0x017E, 0x0178,
    ];
    b.iter()
        .map(|&c| if (0x80..0xA0).contains(&c) { char::from_u32(HIGH[(c - 0x80) as usize]).unwrap() } else { c as char })
        .collect()
}

/// Shared clean-up: trailing spaces/tabs off each line, at most one blank line,
/// trim, cut to `cap` characters.
pub fn finish(text: &str, cap: usize) -> String {
    let lines: Vec<&str> = text.split('\n').map(|l| l.trim_end_matches([' ', '\t'])).collect();
    let mut out = String::with_capacity(text.len());
    let mut newlines = 0;
    for (i, line) in lines.iter().enumerate() {
        if i > 0 {
            newlines += 1;
        }
        if !line.is_empty() {
            for _ in 0..newlines.min(2) {
                out.push('\n');
            }
            newlines = 0;
            out.push_str(line);
        }
    }
    // (leading newlines are dropped above; trailing ones never written)
    let trimmed = out.trim_matches([' ', '\t', '\n']);
    match trimmed.char_indices().nth(cap) {
        Some((i, _)) => trimmed[..i].to_string(),
        None => trimmed.to_string(),
    }
}

// ------------------------------------------------------------------- .doc
pub fn doc(path: &str, cap: usize) -> Result<String> {
    let mut cf = open(path)?;
    let word = read_stream(&mut cf, "WordDocument")?;
    if word.len() < 0x200 || u16_at(&word, 0)? != 0xA5EC {
        return Err(crate::Error("not a Word 97-2003 document".into()));
    }
    let flags = u16_at(&word, 0x0A)?;
    if flags & 0x0100 != 0 {
        return Err(crate::Error("encrypted document".into()));
    }
    let csw = u16_at(&word, 32)? as usize;
    let lw_at = 32 + 2 + csw * 2;
    let cslw = u16_at(&word, lw_at)? as usize;
    let mut total: u64 = 0;
    for k in 3..11 {
        total += u32_at(&word, lw_at + 2 + 4 * k)? as u64; // ccpText ... ccpHdrTxbx
    }
    let fclcb_at = lw_at + 2 + cslw * 4 + 2;
    let fc_clx = u32_at(&word, fclcb_at + 33 * 8)? as usize;
    let lcb_clx = u32_at(&word, fclcb_at + 33 * 8 + 4)? as usize;
    let table = read_stream(&mut cf, if flags & 0x0200 != 0 { "1Table" } else { "0Table" })?;
    let clx = table.get(fc_clx.min(table.len())..(fc_clx + lcb_clx).min(table.len())).unwrap_or(&[]);
    let mut text = String::new();
    for (cp_start, cp_end, fc, compressed) in piece_table(clx)? {
        if cp_start as u64 >= total {
            break;
        }
        let n = (cp_end as u64).min(total).saturating_sub(cp_start as u64) as usize;
        if compressed {
            let a = (fc / 2).min(word.len());
            text.push_str(&cp1252(&word[a..(a + n).min(word.len())]));
        } else {
            let a = fc.min(word.len());
            text.push_str(&utf16le(&word[a..(a + 2 * n).min(word.len())]));
        }
    }
    Ok(finish(&doc_clean(&text), cap))
}

fn piece_table(clx: &[u8]) -> Result<Vec<(u32, u32, usize, bool)>> {
    let mut i = 0;
    while i < clx.len() && clx[i] == 0x01 {
        i += 3 + u16_at(clx, i + 1)? as usize; // Prc, skipped
    }
    if i >= clx.len() || clx[i] != 0x02 {
        return Err(crate::Error("no piece table".into()));
    }
    let lcb = u32_at(clx, i + 1)? as usize;
    let plc = &clx[(i + 5).min(clx.len())..(i + 5 + lcb).min(clx.len())];
    if plc.len() < 4 {
        return Err(crate::Error("no piece table".into()));
    }
    let n = (plc.len() - 4) / 12;
    let mut cps = Vec::with_capacity(n + 1);
    for k in 0..=n {
        cps.push(u32_at(plc, 4 * k)?);
    }
    let mut pieces = Vec::with_capacity(n);
    for k in 0..n {
        let fc_raw = u32_at(plc, 4 * (n + 1) + 8 * k + 2)?;
        pieces.push((cps[k], cps[k + 1], (fc_raw & 0x3FFF_FFFF) as usize, fc_raw & 0x4000_0000 != 0));
    }
    Ok(pieces)
}

/// Remove field codes and control marks; cells -> tabs, rows -> lines.
fn doc_clean(text: &str) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len());
    let mut fields: Vec<bool> = Vec::new(); // per open field: still in its code part?
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        let o = c as u32;
        if o == 0x13 {
            fields.push(true);
        } else if o == 0x14 {
            if let Some(last) = fields.last_mut() {
                *last = false;
            }
        } else if o == 0x15 {
            fields.pop();
        } else if fields.last() == Some(&true) {
            // field code text
        } else if o == 0x07 {
            if i + 1 < chars.len() && chars[i + 1] as u32 == 0x07 {
                out.push('\n');
                i += 1;
            } else {
                out.push('\t');
            }
        } else {
            match o {
                0x0D | 0x0B | 0x0C | 0x0E => out.push('\n'),
                0x09 => out.push('\t'),
                0x1E => out.push('-'),
                0xA0 => out.push(' '),
                _ if o < 0x20 => {}
                _ => out.push(c),
            }
        }
        i += 1;
    }
    out
}

// ------------------------------------------------------------------- .ppt
const MAIN_MASTER: u16 = 0x03F8;
const SLIDE_LIST_WITH_TEXT: u16 = 0x0FF0;
const TEXT_CHARS: u16 = 0x0FA0;
const TEXT_BYTES: u16 = 0x0FA8;

pub fn ppt(path: &str, cap: usize) -> Result<String> {
    let mut cf = open(path)?;
    let data = read_stream(&mut cf, "PowerPoint Document")?;
    let mut parts: Vec<String> = Vec::new();
    ppt_walk(&data, 0, data.len(), &mut parts, 0);
    let joined = parts.iter().map(|p| p.replace('\r', "\n").replace('\u{b}', "\n")).collect::<Vec<_>>().join("\n");
    Ok(finish(&joined, cap))
}

fn ppt_walk(data: &[u8], start: usize, end: usize, parts: &mut Vec<String>, depth: usize) {
    let mut pos = start;
    while pos + 8 <= end {
        let ver_inst = u16::from_le_bytes([data[pos], data[pos + 1]]);
        let rtype = u16::from_le_bytes([data[pos + 2], data[pos + 3]]);
        let length = u32::from_le_bytes([data[pos + 4], data[pos + 5], data[pos + 6], data[pos + 7]]) as usize;
        let body = pos + 8;
        let stop = body.saturating_add(length).min(end);
        if ver_inst & 0x000F == 0x000F {
            let instance = ver_inst >> 4;
            let skip = rtype == MAIN_MASTER || (rtype == SLIDE_LIST_WITH_TEXT && instance == 1);
            if !skip && depth < 64 {
                ppt_walk(data, body, stop, parts, depth + 1);
            }
        } else if rtype == TEXT_CHARS || rtype == TEXT_BYTES {
            let raw = &data[body.min(stop)..stop];
            let text = if rtype == TEXT_CHARS { utf16le(raw) } else { raw.iter().map(|&b| b as char).collect() };
            if text.trim_matches([' ', '\t', '\r', '\n']) != "*" {
                parts.push(text);
            }
        }
        pos = body.saturating_add(length);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finish_matches_python_rules() {
        assert_eq!(finish("\n\n a  \t\n\n\n\nb\t\n\nc\n", 100), "a\n\nb\n\nc");
        assert_eq!(finish("กขค", 2), "กข");
    }

    #[test]
    fn fields_tables_and_marks() {
        let raw = "ก\u{13} HYPERLINK \"http://x\" \u{14}ลิงก์\u{15}ข\rc1\u{7}c2\u{7}\u{7}x\u{1e}y\u{1f}z\u{a0}!";
        assert_eq!(doc_clean(raw), "กลิงก์ข\nc1\tc2\nx-yz !");
    }

    #[test]
    fn cp1252_like_python() {
        assert_eq!(cp1252(b"caf\xe9 \x80 \x81"), "café € \u{FFFD}");
    }
}
