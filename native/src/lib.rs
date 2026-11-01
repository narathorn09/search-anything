//! Fast text extraction for CAHON (docx, xlsx, pptx and the old
//! doc, xls, ppt).
//!
//! Produces exactly the same text as the Python extractors in
//! `cahon/extractors.py` (openpyxl, python-docx, python-pptx), but
//! several times faster and without holding Python's GIL, so the scanner's
//! threads really run in parallel. `tests/test_native.py` checks the outputs
//! are identical.

pub mod docx;
pub mod legacy;
pub mod ooxml;
pub mod pptx;
pub mod xlsx;

/// Cap on stored text per file — the same rules as `_Collector` in Python:
/// pieces are kept until the running size (characters + 1 per piece) reaches
/// the cap, then the joined text is cut to the cap.
pub struct Collector {
    parts: Vec<String>,
    size: usize,
    cap: usize,
}

impl Collector {
    pub fn new(cap: usize) -> Self {
        Collector { parts: Vec::new(), size: 0, cap }
    }

    pub fn full(&self) -> bool {
        self.size >= self.cap
    }

    pub fn add(&mut self, text: String) {
        if !text.is_empty() && !self.full() {
            self.size += text.chars().count() + 1;
            self.parts.push(text);
        }
    }

    pub fn text(self) -> String {
        let joined = self.parts.join("\n");
        match joined.char_indices().nth(self.cap) {
            Some((i, _)) => joined[..i].to_string(),
            None => joined,
        }
    }
}

#[derive(Debug)]
pub struct Error(pub String);

impl<E: std::fmt::Display> From<E> for Error {
    fn from(e: E) -> Self {
        Error(e.to_string())
    }
}

pub type Result<T> = std::result::Result<T, Error>;

#[cfg(feature = "python")]
mod python {
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    fn run(py: Python<'_>, f: impl FnOnce() -> crate::Result<String> + Send) -> PyResult<String> {
        // The work needs no Python objects: let other threads run meanwhile.
        py.detach(f).map_err(|e| PyValueError::new_err(e.0))
    }

    /// Text of an .xlsx/.xlsm workbook (same as the openpyxl extractor).
    #[pyfunction]
    fn xlsx_text(py: Python<'_>, path: String, cap: usize) -> PyResult<String> {
        run(py, move || crate::xlsx::extract(&path, cap))
    }

    /// Text of a .docx document (same as the python-docx extractor).
    #[pyfunction]
    fn docx_text(py: Python<'_>, path: String, cap: usize) -> PyResult<String> {
        run(py, move || crate::docx::extract(&path, cap))
    }

    /// Text of a .pptx presentation (same as the python-pptx extractor).
    #[pyfunction]
    fn pptx_text(py: Python<'_>, path: String, cap: usize) -> PyResult<String> {
        run(py, move || crate::pptx::extract(&path, cap))
    }

    /// Text of an old .xls workbook (same as the Python/xlrd reader).
    #[pyfunction]
    fn xls_text(py: Python<'_>, path: String, cap: usize) -> PyResult<String> {
        run(py, move || crate::xlsx::extract_xls(&path, cap))
    }

    /// Text of an old .doc document (same as cahon/legacy.py).
    #[pyfunction]
    fn doc_text(py: Python<'_>, path: String, cap: usize) -> PyResult<String> {
        run(py, move || crate::legacy::doc(&path, cap))
    }

    /// Text of an old .ppt presentation (same as cahon/legacy.py).
    #[pyfunction]
    fn ppt_text(py: Python<'_>, path: String, cap: usize) -> PyResult<String> {
        run(py, move || crate::legacy::ppt(&path, cap))
    }

    #[pymodule]
    fn cahon_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(xls_text, m)?)?;
        m.add_function(wrap_pyfunction!(doc_text, m)?)?;
        m.add_function(wrap_pyfunction!(ppt_text, m)?)?;
        m.add_function(wrap_pyfunction!(xlsx_text, m)?)?;
        m.add_function(wrap_pyfunction!(docx_text, m)?)?;
        m.add_function(wrap_pyfunction!(pptx_text, m)?)?;
        m.add("__version__", env!("CARGO_PKG_VERSION"))?;
        Ok(())
    }
}
