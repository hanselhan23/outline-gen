"""PDF processing module for bookmark extraction, splitting, and text extraction."""

import fitz  # PyMuPDF
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import tempfile
import pytesseract
from PIL import Image
import io


class Bookmark:
    """Represents a PDF bookmark with hierarchy information."""

    def __init__(self, title: str, page: int, level: int):
        self.title = title
        self.page = page  # 0-indexed
        self.level = level
        self.children: List[Bookmark] = []

    def __repr__(self):
        return f"Bookmark(title={self.title}, page={self.page}, level={self.level})"


class PDFProcessor:
    """Handles PDF operations including bookmark extraction and splitting."""

    def __init__(self, pdf_path: str, use_ocr: bool = True):
        self.pdf_path = Path(pdf_path)
        self.doc = fitz.open(pdf_path)
        self.use_ocr = use_ocr
        self._is_scanned = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the PDF document."""
        if self.doc:
            self.doc.close()

    def extract_bookmarks(self) -> List[Bookmark]:
        """Extract all bookmarks from the PDF with hierarchy."""
        toc = self.doc.get_toc()  # Returns list of [level, title, page]
        bookmarks = []

        for level, title, page in toc:
            # PyMuPDF returns 1-indexed pages, convert to 0-indexed
            bookmark = Bookmark(title=title, page=page - 1, level=level)
            bookmarks.append(bookmark)

        return bookmarks

    def get_min_level_bookmarks(self, bookmarks: List[Bookmark]) -> List[Bookmark]:
        """Get bookmarks at the minimum (top) level."""
        if not bookmarks:
            return []

        min_level = min(b.level for b in bookmarks)
        return [b for b in bookmarks if b.level == min_level]

    def split_by_bookmarks(self, bookmarks: List[Bookmark]) -> List[Tuple[Bookmark, Path, int]]:
        """
        Split PDF by bookmarks and return list of (bookmark, temp_file_path, page_offset).
        Each section includes pages from bookmark to next bookmark (or end).
        page_offset is the starting page number in the original PDF (0-indexed).
        """
        if not bookmarks:
            return []

        # Sort bookmarks by page
        sorted_bookmarks = sorted(bookmarks, key=lambda b: b.page)
        sections = []

        for i, bookmark in enumerate(sorted_bookmarks):
            # Determine end page
            if i < len(sorted_bookmarks) - 1:
                end_page = sorted_bookmarks[i + 1].page - 1
            else:
                end_page = len(self.doc) - 1

            # Create temporary PDF for this section
            temp_pdf = tempfile.NamedTemporaryFile(
                mode='wb',
                suffix='.pdf',
                delete=False
            )
            temp_path = Path(temp_pdf.name)
            temp_pdf.close()

            # Extract pages
            new_doc = fitz.open()
            new_doc.insert_pdf(
                self.doc,
                from_page=bookmark.page,
                to_page=end_page
            )
            new_doc.save(temp_path)
            new_doc.close()

            # Store bookmark, path, and page offset (starting page in original PDF)
            sections.append((bookmark, temp_path, bookmark.page))

        return sections

    def is_scanned_pdf(self, sample_pages: int = 3) -> bool:
        """
        Check if PDF is scanned (image-based) by sampling pages.

        Args:
            sample_pages: Number of pages to sample for checking

        Returns:
            True if PDF appears to be scanned, False otherwise
        """
        if self._is_scanned is not None:
            return self._is_scanned

        sample_count = min(sample_pages, len(self.doc))
        text_found = False

        # Check middle pages to avoid cover/blank pages
        start_page = max(0, len(self.doc) // 4)
        for i in range(sample_count):
            page_num = start_page + i
            if page_num >= len(self.doc):
                break

            page = self.doc[page_num]
            text = page.get_text().strip()

            if len(text) > 100:  # If we find substantial text, it's not scanned
                text_found = True
                break

        self._is_scanned = not text_found
        return self._is_scanned

    def extract_text_with_ocr(self, page_num: int, lang: str = 'chi_sim+eng') -> str:
        """
        Extract text from a page using OCR.

        Args:
            page_num: Page number (0-indexed)
            lang: Tesseract language code (default: Chinese simplified + English)

        Returns:
            Extracted text
        """
        page = self.doc[page_num]

        # Render page to image at higher resolution for better OCR
        mat = fitz.Matrix(2, 2)  # 2x zoom for better quality
        pix = page.get_pixmap(matrix=mat)

        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Perform OCR
        try:
            text = pytesseract.image_to_string(img, lang=lang)
            return text
        except Exception as e:
            # Fallback to empty string if OCR fails
            return f"[OCR failed: {str(e)}]"

    def extract_text_with_pages(self, max_pages: Optional[int] = None, page_offset: int = 0) -> str:
        """
        Extract text from PDF with page number markers.
        Automatically uses OCR for scanned PDFs.

        Args:
            max_pages: Maximum number of pages to process (None for all)
            page_offset: Offset to add to page numbers (for split PDFs)

        Format: [Page N] followed by page content.
        """
        text_parts = []
        is_scanned = self.is_scanned_pdf()

        page_count = len(self.doc)
        if max_pages:
            page_count = min(page_count, max_pages)

        for page_num in range(page_count):
            page = self.doc[page_num]

            # Try regular text extraction first
            page_text = page.get_text().strip()

            # Use OCR if no text found and OCR is enabled
            if not page_text and self.use_ocr and is_scanned:
                page_text = self.extract_text_with_ocr(page_num)

            # Add page marker with offset (1-indexed for user readability)
            actual_page_num = page_num + page_offset + 1
            text_parts.append(f"[Page {actual_page_num}]")
            if page_text:
                text_parts.append(page_text)
            text_parts.append("\n")

        return "\n".join(text_parts)

    def extract_text_with_pages_range(self, start_page: int, end_page: int) -> str:
        """
        Extract text with [Page N] markers for a 1-indexed page range (inclusive).
        """
        if start_page <= 0 and end_page <= 0:
            return ""

        page_count = len(self.doc)
        if page_count == 0:
            return ""

        start_idx = max(start_page - 1, 0)
        end_idx = min(end_page - 1, page_count - 1)
        if end_idx < start_idx:
            return ""

        text_parts = []
        is_scanned = self.is_scanned_pdf()

        for page_num in range(start_idx, end_idx + 1):
            page = self.doc[page_num]
            page_text = page.get_text().strip()

            if not page_text and self.use_ocr and is_scanned:
                page_text = self.extract_text_with_ocr(page_num)

            actual_page_num = page_num + 1
            text_parts.append(f"[Page {actual_page_num}]")
            if page_text:
                text_parts.append(page_text)
            text_parts.append("\n")

        return "\n".join(text_parts)

    def extract_text_for_page_range(
        self,
        start_page: int,
        end_page: int
    ) -> str:
        """
        Extract plain text from a given 1-indexed page range (inclusive).

        This is similar to extract_text_with_pages, but:
        - Uses global 1-indexed page numbers for start/end.
        - Does not insert [Page N] markers, only concatenates page texts.
        """
        if start_page <= 0 and end_page <= 0:
            return ""

        page_count = len(self.doc)
        if page_count == 0:
            return ""

        # Normalize to 0-indexed bounds within the document range.
        start_idx = max(start_page - 1, 0)
        end_idx = min(end_page - 1, page_count - 1)

        if end_idx < start_idx:
            return ""

        text_parts = []
        is_scanned = self.is_scanned_pdf()

        for page_num in range(start_idx, end_idx + 1):
            page = self.doc[page_num]

            page_text = page.get_text().strip()
            if not page_text and self.use_ocr and is_scanned:
                page_text = self.extract_text_with_ocr(page_num)

            if page_text:
                text_parts.append(page_text)

        return "\n\n".join(text_parts)

    def get_page_count(self) -> int:
        """Get total number of pages in the PDF."""
        return len(self.doc)

    def get_bookmarks_in_range(
        self,
        bookmarks: List[Bookmark],
        start_page: int,
        end_page: int,
        target_level: Optional[int] = None
    ) -> List[Bookmark]:
        """
        Get bookmarks within a page range, optionally filtered by level.
        Pages are 0-indexed.
        """
        filtered = [
            b for b in bookmarks
            if start_page <= b.page <= end_page
        ]

        if target_level is not None:
            filtered = [b for b in filtered if b.level == target_level]

        return filtered
