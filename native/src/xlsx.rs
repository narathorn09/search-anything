//! .xlsx/.xlsm text, matching openpyxl (read_only, data_only) as used by
//! `extractors._xlsx`: per worksheet "# title", then each row's non-empty
//! cells joined with "\t", values printed the way Python's str() prints them.

use calamine::{open_workbook, Data, Reader, SheetType, Xls, Xlsx};

use crate::{Collector, Result};

/// Python's repr()/str() of a float: shortest round-trip digits, fixed notation
/// for exponents in [-4, 16), otherwise "1.5e-05" / "1e+16".
pub fn py_float(v: f64) -> String {
    if v.is_nan() {
        return "nan".into();
    }
    if v.is_infinite() {
        return if v > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if v == 0.0 {
        return if v.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    let sci = format!("{:e}", v); // e.g. "-1.2345e-5", shortest digits
    let (mant, exp) = sci.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let neg = mant.starts_with('-');
    let digits: String = mant.chars().filter(|c| c.is_ascii_digit()).collect();
    let sign = if neg { "-" } else { "" };
    if (-4..16).contains(&exp) {
        let point = exp + 1; // digits before the decimal point
        let body = if point <= 0 {
            format!("0.{}{}", "0".repeat((-point) as usize), digits)
        } else if point as usize >= digits.len() {
            format!("{}{}.0", digits, "0".repeat(point as usize - digits.len()))
        } else {
            format!("{}.{}", &digits[..point as usize], &digits[point as usize..])
        };
        format!("{sign}{body}")
    } else {
        let m = if digits.len() > 1 { format!("{}.{}", &digits[..1], &digits[1..]) } else { digits };
        format!("{sign}{m}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

/// openpyxl gives int for numbers written without "." or exponent (what Excel
/// writes for whole numbers), float otherwise.
fn py_number(v: f64) -> String {
    if v.fract() == 0.0 && v.abs() < 1e16 {
        format!("{}", v as i64)
    } else {
        py_float(v)
    }
}

fn two(n: i64) -> String {
    format!("{:02}", n)
}

fn micro_suffix(us: i64) -> String {
    if us == 0 { String::new() } else { format!(".{:06}", us) }
}

/// openpyxl `from_excel` + Python str(): datetime, time or timedelta text.
pub fn py_excel_date(value: f64, duration: bool) -> String {
    py_excel_date_epoch(value, duration, false)
}

/// Same, choosing the workbook's date system (1904 = old Mac Excel).
pub fn py_excel_date_epoch(value: f64, duration: bool, is_1904: bool) -> String {
    if duration {
        // timedelta(days=value), rounded to milliseconds when it has microseconds.
        let total_us = (value * 86_400_000_000.0).round() as i64;
        let mut us = total_us;
        if us.rem_euclid(1_000_000) != 0 {
            let secs = (us as f64 / 1e6).floor() as i64;
            let frac = us - secs * 1_000_000;
            us = secs * 1_000_000 + ((frac as f64 / 1000.0).round() as i64) * 1000;
        }
        let days = us.div_euclid(86_400_000_000);
        let rest = us.rem_euclid(86_400_000_000);
        let (h, m, s, f) = (rest / 3_600_000_000, rest / 60_000_000 % 60, rest / 1_000_000 % 60, rest % 1_000_000);
        let clock = format!("{}:{}:{}{}", h, two(m), two(s), micro_suffix(f));
        return match days {
            0 => clock,
            1 | -1 => format!("{days} day, {clock}"),
            _ => format!("{days} days, {clock}"),
        };
    }
    let mut day = value.floor();
    let fraction = value - day;
    let ms = (fraction * 86_400_000.0).round() as i64;
    if (0.0..1.0).contains(&value) && ms < 86_400_000 {
        let (h, m, s) = (ms / 3_600_000, ms / 60_000 % 60, ms / 1000 % 60);
        return format!("{}:{}:{}{}", two(h), two(m), two(s), micro_suffix(ms % 1000 * 1000));
    }
    if value > 0.0 && value < 60.0 && !is_1904 {
        day += 1.0;
    }
    // epoch (1899-12-30, or 1904-01-01) + day days + ms
    let total_ms = (day as i64) * 86_400_000 + ms;
    let days = total_ms.div_euclid(86_400_000);
    let rest = total_ms.rem_euclid(86_400_000);
    let epoch = if is_1904 { -24_107 } else { -25_569 }; // days from 1970-01-01
    let (y, mo, d) = civil_from_days(days + epoch);
    format!("{:04}-{}-{} {}:{}:{}{}", y, two(mo), two(d), two(rest / 3_600_000), two(rest / 60_000 % 60),
            two(rest / 1000 % 60), micro_suffix(rest % 1000 * 1000))
}

/// Days since 1970-01-01 -> (year, month, day). (Howard Hinnant's algorithm.)
fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

fn cell_text(cell: &Data) -> Option<String> {
    let s = match cell {
        Data::Empty => return None,
        Data::String(s) => s.clone(),
        Data::Float(f) => py_number(*f),
        Data::Int(i) => i.to_string(),
        Data::Bool(b) => if *b { "True".into() } else { "False".into() },
        Data::DateTime(dt) => py_excel_date(dt.as_f64(), dt.is_duration()),
        Data::DateTimeIso(s) => s.replacen('T', " ", 1),
        Data::DurationIso(s) => s.clone(),
        Data::Error(e) => e.to_string(),
    };
    if s.is_empty() { None } else { Some(s) }
}

/// .xls cells, like xlrd + the Python reader: every date-formatted number is a
/// date (xlrd has no separate duration type), in the workbook's date system.
fn xls_cell_text(cell: &Data) -> Option<String> {
    match cell {
        Data::DateTime(dt) => {
            let v = dt.as_f64();
            // calamine keeps the 1904 flag private; its datetime reveals it.
            let is_1904 = dt
                .as_datetime()
                .map(|d| {
                    let days = d.and_utc().timestamp().div_euclid(86_400) + 25_569;
                    (days as f64 - v).abs() > 1000.0
                })
                .unwrap_or(false);
            Some(py_excel_date_epoch(v, false, is_1904))
        }
        other => cell_text(other),
    }
}

pub fn extract_xls(path: &str, cap: usize) -> Result<String> {
    let mut wb: Xls<_> = open_workbook(path)?;
    let sheets: Vec<String> = wb
        .sheets_metadata()
        .iter()
        .filter(|s| s.typ == SheetType::WorkSheet)
        .map(|s| s.name.clone())
        .collect();
    let mut out = Collector::new(cap);
    for name in sheets {
        out.add(format!("# {name}"));
        let range = wb.worksheet_range(&name)?;
        for row in range.rows() {
            let cells: Vec<String> = row.iter().filter_map(xls_cell_text).collect();
            if !cells.is_empty() {
                out.add(cells.join("\t"));
            }
            if out.full() {
                break;
            }
        }
    }
    Ok(out.text())
}

pub fn extract(path: &str, cap: usize) -> Result<String> {
    let mut wb: Xlsx<_> = open_workbook(path)?;
    let sheets: Vec<String> = wb
        .sheets_metadata()
        .iter()
        .filter(|s| s.typ == SheetType::WorkSheet)
        .map(|s| s.name.clone())
        .collect();
    let mut out = Collector::new(cap);
    for name in sheets {
        out.add(format!("# {name}"));
        let range = wb.worksheet_range(&name)?;
        for row in range.rows() {
            let cells: Vec<String> = row.iter().filter_map(cell_text).collect();
            if !cells.is_empty() {
                out.add(cells.join("\t"));
            }
            if out.full() {
                break;
            }
        }
    }
    Ok(out.text())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats_print_like_python() {
        for (v, s) in [(0.1, "0.1"), (1234.5, "1234.5"), (1e-5, "1e-05"), (1.5e-7, "1.5e-07"), (0.0001, "0.0001"),
                       (1e16, "1e+16"), (123456789012345.6, "123456789012345.6"), (2.5e20, "2.5e+20"),
                       (-0.30000000000000004, "-0.30000000000000004"), (100.0, "100.0")] {
            assert_eq!(py_float(v), s);
        }
        assert_eq!(py_number(5.0), "5");
        assert_eq!(py_number(5.25), "5.25");
    }

    #[test]
    fn dates_print_like_openpyxl() {
        assert_eq!(py_excel_date(45292.0, false), "2024-01-01 00:00:00");
        assert_eq!(py_excel_date(45292.5, false), "2024-01-01 12:00:00");
        assert_eq!(py_excel_date(0.75, false), "18:00:00");
        assert_eq!(py_excel_date(1.0, false), "1900-01-01 00:00:00");
        assert_eq!(py_excel_date(1.5, true), "1 day, 12:00:00");
        assert_eq!(py_excel_date(0.25, true), "6:00:00");
    }
}
