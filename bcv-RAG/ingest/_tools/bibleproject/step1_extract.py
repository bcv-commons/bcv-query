#!/usr/bin/env python3
"""
BibleProject PDF Metadata Extractor - Step 1

Extracts comprehensive metadata from BibleProject PDFs:
- Full text extraction with page-by-page structure
- Bible reference detection and extraction
- Video timestamp preservation
- Mirrored directory structure under imports/tbp/extracted/

This is Step 1 of a two-step process:
  Step 1 (this script): Extract metadata → imports/tbp/extracted/{folder}/{file}.json
  Step 2 (extract_tbp_step2_chunking.py): Intelligent chunking → imports/tbp/chunks/

No chunking is performed in this step - just metadata extraction.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import PyPDF2
except ImportError:
    print("PyPDF2 not found. Installing...")
    import subprocess

    subprocess.check_call(["pip", "install", "PyPDF2", "-q"])
    import PyPDF2


class BibleReferenceParser:
    """Parse and manage Bible reference information from documents."""

    # Bible book patterns
    BOOK_PATTERNS = [
        # Multi-word books
        r"1\s*Chronicles?",
        r"2\s*Chronicles?",
        r"1\s*Corinthians?",
        r"2\s*Corinthians?",
        r"1\s*Kings?",
        r"2\s*Kings?",
        r"1\s*Peter",
        r"2\s*Peter",
        r"1\s*Samuel",
        r"2\s*Samuel",
        r"1\s*Thessalonians?",
        r"2\s*Thessalonians?",
        r"1\s*Timothy",
        r"2\s*Timothy",
        r"1\s*John",
        r"2\s*John",
        r"3\s*John",
        r"Song\s+of\s+Songs?",
        r"Song\s+of\s+Solomon",
        # Single word books
        r"Genesis",
        r"Exodus",
        r"Leviticus",
        r"Numbers",
        r"Deuteronomy",
        r"Joshua",
        r"Judges",
        r"Ruth",
        r"Ezra",
        r"Nehemiah",
        r"Esther",
        r"Job",
        r"Psalms?",
        r"Proverbs?",
        r"Ecclesiastes",
        r"Isaiah",
        r"Jeremiah",
        r"Lamentations",
        r"Ezekiel",
        r"Daniel",
        r"Hosea",
        r"Joel",
        r"Amos",
        r"Obadiah",
        r"Jonah",
        r"Micah",
        r"Nahum",
        r"Habakkuk",
        r"Zephaniah",
        r"Haggai",
        r"Zechariah",
        r"Malachi",
        r"Matthew",
        r"Mark",
        r"Luke",
        r"John",
        r"Acts",
        r"Romans?",
        r"Galatians?",
        r"Ephesians?",
        r"Philippians?",
        r"Colossians?",
        r"Titus",
        r"Philemon",
        r"Hebrews?",
        r"James",
        r"Jude",
        r"Revelation",
    ]

    # Build comprehensive Bible reference pattern
    BOOK_PATTERN = r"(?:" + "|".join(BOOK_PATTERNS) + r")"

    # Reference patterns
    REFERENCE_PATTERNS = [
        # Full reference with chapter and verse ranges
        rf"({BOOK_PATTERN})\s+(\d+):(\d+)[-–](\d+)",
        # Full reference with chapter and single verse
        rf"({BOOK_PATTERN})\s+(\d+):(\d+)",
        # Chapter reference only
        rf"({BOOK_PATTERN})\s+(\d+)",
        # Multiple chapters
        rf"({BOOK_PATTERN})\s+(\d+)[-–](\d+)",
    ]

    @classmethod
    def find_all_references(cls, text: str) -> List[Dict]:
        """Find all Bible references in text with their positions."""
        references = []
        seen = set()  # Avoid duplicates

        for pattern in cls.REFERENCE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                ref_text = match.group(0)

                # Skip if we've seen this exact reference
                if ref_text in seen:
                    continue
                seen.add(ref_text)

                ref_data = {
                    "text": ref_text,
                    "position": match.start(),
                    "book": match.group(1),
                }

                # Parse chapter and verse info
                groups = match.groups()
                if len(groups) >= 3:
                    ref_data["chapter"] = int(groups[1])
                    if groups[2].isdigit():
                        ref_data["verse_start"] = int(groups[2])
                        if len(groups) >= 4 and groups[3] and groups[3].isdigit():
                            ref_data["verse_end"] = int(groups[3])
                elif len(groups) >= 2 and groups[1].isdigit():
                    ref_data["chapter"] = int(groups[1])

                references.append(ref_data)

        return sorted(references, key=lambda x: x["position"])

    @classmethod
    def extract_references_from_page(cls, page_text: str) -> List[Dict]:
        """Extract references with context from a page."""
        references = cls.find_all_references(page_text)

        # Enhance with context
        for ref in references:
            pos = ref["position"]
            # Get surrounding context (50 chars before and after)
            context_start = max(0, pos - 50)
            context_end = min(len(page_text), pos + len(ref["text"]) + 50)
            ref["context"] = page_text[context_start:context_end].strip()

        return references


class TimestampParser:
    """Parse and manage timestamp information from transcripts."""

    TIMESTAMP_PATTERNS = [
        r"(\d{1,2}:\d{2}:\d{2})[-–](\d{1,2}:\d{2}:\d{2})",  # HH:MM:SS-HH:MM:SS
        r"(\d{1,2}:\d{2})[-–](\d{1,2}:\d{2})",  # MM:SS-MM:SS
    ]

    @staticmethod
    def parse_timestamp(text: str) -> Optional[Tuple[str, str]]:
        """Extract start and end timestamps from text."""
        for pattern in TimestampParser.TIMESTAMP_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return (match.group(1), match.group(2))
        return None

    @staticmethod
    def timestamp_to_seconds(ts: str) -> int:
        """Convert timestamp string to seconds."""
        parts = ts.split(":")
        if len(parts) == 3:  # HH:MM:SS
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:  # MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        return 0

    @staticmethod
    def find_all_timestamps(text: str) -> List[Tuple[int, str, str]]:
        """Find all timestamp ranges in text with their positions."""
        timestamps = []
        for pattern in TimestampParser.TIMESTAMP_PATTERNS:
            for match in re.finditer(pattern, text):
                pos = match.start()
                start_ts = match.group(1)
                end_ts = match.group(2)
                timestamps.append((pos, start_ts, end_ts))
        return sorted(timestamps, key=lambda x: x[0])


class TBPMetadataExtractor:
    """Extract comprehensive metadata from BibleProject PDFs."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.files_path = base_path / "files"
        self.manifest_path = base_path / "metadata" / "download-manifest.json"
        self.config_path = base_path / "config" / "tbp.json"

        # Output directories
        self.extracted_dir = base_path / "extracted"

        # Load manifest and config
        self.manifest = self.load_manifest()
        self.config = self.load_config()
        self.file_metadata = self.build_file_metadata_map()

        # Statistics
        self.stats = {
            "total_pdfs": 0,
            "extracted": 0,
            "failed": 0,
            "total_pages": 0,
            "with_timestamps": 0,
            "with_bible_refs": 0,
            "total_bible_refs": 0,
        }
        self.failed_files = []

        # Category statistics
        self.category_stats = {}
        self.type_stats = {}
        self.series_stats = {}

    def load_manifest(self) -> Dict:
        """Load manifest.json if it exists."""
        if self.manifest_path.exists():
            with open(self.manifest_path, "r") as f:
                return json.load(f)
        return {"resources": []}

    def load_config(self) -> Dict:
        """Load tbp.json config if it exists."""
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                return json.load(f)
        return {"categorization_rules": [], "timestamp_sources": []}

    def build_file_metadata_map(self) -> Dict[str, Dict]:
        """Build a map from sanitized filename to manifest metadata."""
        file_map = {}
        for resource in self.manifest.get("resources", []):
            sanitized = resource.get("sanitized_filename", "")
            if sanitized:
                file_map[sanitized] = {
                    "original_url": resource.get("url", ""),
                    "original_path": resource.get("original_path", ""),
                    "folders": resource.get("sanitized_folders", []),
                    "folder_path": resource.get("sanitized_path", ""),
                }
        return file_map

    def get_relative_path(self, pdf_path: Path) -> str:
        """Get relative path from files directory."""
        try:
            rel_path = pdf_path.relative_to(self.files_path)
            return str(rel_path.parent) if str(rel_path.parent) != "." else ""
        except ValueError:
            return ""

    def apply_categorization_rules(self, folder_path: str) -> Tuple[str, str]:
        """Apply categorization rules from config to determine type and series."""
        rules = self.config.get("categorization_rules", [])

        for rule in rules:
            pattern = rule.get("folder_pattern", "")
            if re.match(pattern, folder_path):
                doc_type = rule.get("type", "Theme-Resource")
                series = rule.get("series", "General")

                # Handle capture group substitution in series
                match = re.match(pattern, folder_path)
                if match and "$1" in series:
                    series = series.replace("$1", match.group(1) if match.lastindex else "")

                return doc_type, series

        # Default categorization
        return "Theme-Resource", "General"

    def categorize_by_folder(self, pdf_path: Path) -> Dict[str, str]:
        """Categorize document based on folder structure."""
        rel_path = self.get_relative_path(pdf_path)
        primary_folder = pdf_path.parent.name

        # Get manifest metadata if available
        filename = pdf_path.name
        manifest_data = self.file_metadata.get(filename, {})

        # Apply categorization rules
        doc_type, series = self.apply_categorization_rules(rel_path)

        # Determine category for grouping
        if rel_path:
            category = rel_path.split("/")[0]
        else:
            category = primary_folder

        # Map common categories to standardized names
        category_map = {
            "Script-References": "Script-References",
            "Study-Notes": "Study-Notes",
            "Insight-Videos": "Insight-Videos",
            "Deuterocanon-Apocrypha": "Deuterocanon-Apocrypha",
            "advent": "Advent",
        }

        category = category_map.get(category, category)

        return {
            "category": category,
            "type": doc_type,
            "series": series,
            "primary_folder": primary_folder,
            "folder_path": rel_path,
            "original_url": manifest_data.get("original_url", ""),
            "original_path": manifest_data.get("original_path", ""),
        }

    def clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)

        # Remove null bytes and control characters
        text = text.replace("\x00", "")
        text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)

        # Normalize quotes
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace("'", "'").replace("'", "'")

        # Remove page numbers
        text = re.sub(r"\bPage \d+\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b\d+\s*/\s*\d+\b", "", text)

        return text.strip()

    def extract_pdf_metadata(self, pdf_path: Path) -> Optional[Dict]:
        """Extract comprehensive metadata from a single PDF."""
        try:
            with open(pdf_path, "rb") as file:
                reader = PyPDF2.PdfReader(file)

                if len(reader.pages) == 0:
                    return None

                # Get categorization metadata
                doc_info = self.categorize_by_folder(pdf_path)

                # Extract title from filename
                filename = pdf_path.stem
                # Remove common suffixes
                for suffix in ["_Transcript", "_Script-References", "_Study-Notes", "_SR"]:
                    if filename.endswith(suffix):
                        filename = filename[: -len(suffix)]
                        break

                title = filename.replace("-", " ").replace("_", " ").strip()

                # Extract text from all pages with references
                pages_data = []
                all_bible_refs = []
                all_timestamps = []

                for page_num, page in enumerate(reader.pages, 1):
                    text = page.extract_text()
                    if text:
                        cleaned = self.clean_text(text)
                        if cleaned:
                            # Extract Bible references from this page
                            page_refs = BibleReferenceParser.extract_references_from_page(cleaned)

                            # Extract timestamps from this page
                            page_timestamps = TimestampParser.find_all_timestamps(cleaned)

                            pages_data.append(
                                {
                                    "page": page_num,
                                    "text": cleaned,
                                    "word_count": len(cleaned.split()),
                                    "char_count": len(cleaned),
                                    "bible_references": page_refs,
                                    "timestamps": [
                                        {
                                            "start": ts[1],
                                            "end": ts[2],
                                            "start_seconds": TimestampParser.timestamp_to_seconds(
                                                ts[1]
                                            ),
                                            "end_seconds": TimestampParser.timestamp_to_seconds(
                                                ts[2]
                                            ),
                                            "position": ts[0],
                                        }
                                        for ts in page_timestamps
                                    ],
                                }
                            )

                            # Add to document-level references
                            for ref in page_refs:
                                ref["page"] = page_num
                                all_bible_refs.append(ref)

                            # Add to document-level timestamps
                            for ts in page_timestamps:
                                all_timestamps.append(
                                    {
                                        "start": ts[1],
                                        "end": ts[2],
                                        "start_seconds": TimestampParser.timestamp_to_seconds(
                                            ts[1]
                                        ),
                                        "end_seconds": TimestampParser.timestamp_to_seconds(ts[2]),
                                        "position": ts[0],
                                        "page": page_num,
                                    }
                                )

                if not pages_data:
                    return None

                # Build full text
                full_text = " ".join([p["text"] for p in pages_data])

                # Features
                has_timestamps = len(all_timestamps) > 0
                has_bible_refs = len(all_bible_refs) > 0

                return {
                    "file_info": {
                        "filename": pdf_path.name,
                        "title": title,
                        "category": doc_info["category"],
                        "type": doc_info["type"],
                        "series": doc_info["series"],
                        "primary_folder": doc_info["primary_folder"],
                        "folder_path": doc_info["folder_path"],
                        "original_url": doc_info["original_url"],
                        "original_path": doc_info["original_path"],
                    },
                    "content_stats": {
                        "pages": len(reader.pages),
                        "word_count": len(full_text.split()),
                        "char_count": len(full_text),
                    },
                    "features": {
                        "has_timestamps": has_timestamps,
                        "timestamp_count": len(all_timestamps),
                        "has_bible_refs": has_bible_refs,
                        "bible_ref_count": len(all_bible_refs),
                    },
                    "bible_references": all_bible_refs,
                    "timestamps": all_timestamps,
                    "pages": pages_data,
                    "full_text": full_text,
                }

        except Exception as e:
            print(f"  ✗ Error extracting {pdf_path.name}: {e}")
            self.failed_files.append({"file": str(pdf_path), "error": str(e)})
            return None

    def save_metadata_file(self, metadata: Dict, pdf_path: Path) -> Path:
        """Save metadata file in mirrored directory structure."""
        # Get relative path from files directory
        rel_path = pdf_path.relative_to(self.files_path)

        # Create mirrored directory structure
        extracted_file_dir = self.extracted_dir / rel_path.parent
        extracted_file_dir.mkdir(parents=True, exist_ok=True)

        # Create metadata filename (replace .pdf with .json)
        metadata_filename = pdf_path.stem + ".json"
        metadata_path = extracted_file_dir / metadata_filename

        # Save metadata file
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return metadata_path

    def update_category_stats(self, category: str, metadata: Dict):
        """Update statistics for a category."""
        if category not in self.category_stats:
            self.category_stats[category] = {
                "count": 0,
                "pages": 0,
                "words": 0,
                "bible_refs": 0,
                "timestamps": 0,
            }

        stats = self.category_stats[category]
        stats["count"] += 1
        stats["pages"] += metadata["content_stats"]["pages"]
        stats["words"] += metadata["content_stats"]["word_count"]
        stats["bible_refs"] += metadata["features"]["bible_ref_count"]
        stats["timestamps"] += metadata["features"]["timestamp_count"]

    def update_type_stats(self, doc_type: str, metadata: Dict):
        """Update statistics for a document type."""
        if doc_type not in self.type_stats:
            self.type_stats[doc_type] = {
                "count": 0,
                "pages": 0,
                "words": 0,
                "bible_refs": 0,
                "timestamps": 0,
            }

        stats = self.type_stats[doc_type]
        stats["count"] += 1
        stats["pages"] += metadata["content_stats"]["pages"]
        stats["words"] += metadata["content_stats"]["word_count"]
        stats["bible_refs"] += metadata["features"]["bible_ref_count"]
        stats["timestamps"] += metadata["features"]["timestamp_count"]

    def process_pdfs(self):
        """Process all PDFs and extract metadata."""
        # Clean up old extracted directory if it exists
        if self.extracted_dir.exists():
            print(f"🗑️  Cleaning up old extracted directory...")
            import shutil

            shutil.rmtree(self.extracted_dir)

        # Create fresh extracted directory
        self.extracted_dir.mkdir(parents=True, exist_ok=True)

        # Find all PDFs
        pdf_files = sorted(self.files_path.rglob("*.pdf"))
        self.stats["total_pdfs"] = len(pdf_files)

        print(f"\n🔍 Found {len(pdf_files)} PDF files")
        print(f"📂 Base path: {self.base_path}")
        print(f"📂 Files path: {self.files_path}")
        print(f"📋 Using manifest: {self.manifest_path.exists()}")
        print(f"⚙️  Using config: {self.config_path.exists()}")
        print(f"📁 Output: {self.extracted_dir}")
        print(f"\n{'=' * 70}")
        print("Starting metadata extraction (Step 1 - No chunking)")
        print(f"{'=' * 70}")

        for pdf_path in pdf_files:
            # Show progress
            rel_path = pdf_path.relative_to(self.files_path)
            print(f"\n📄 {rel_path}")

            metadata = self.extract_pdf_metadata(pdf_path)

            if not metadata:
                self.stats["failed"] += 1
                continue

            self.stats["extracted"] += 1
            self.stats["total_pages"] += metadata["content_stats"]["pages"]

            if metadata["features"]["has_timestamps"]:
                self.stats["with_timestamps"] += 1

            if metadata["features"]["has_bible_refs"]:
                self.stats["with_bible_refs"] += 1
                self.stats["total_bible_refs"] += metadata["features"]["bible_ref_count"]

            # Update statistics
            self.update_category_stats(metadata["file_info"]["category"], metadata)
            self.update_type_stats(metadata["file_info"]["type"], metadata)

            # Save metadata file in mirrored structure
            metadata_path = self.save_metadata_file(metadata, pdf_path)
            rel_metadata = metadata_path.relative_to(self.base_path)

            print(
                f"  ✓ {metadata['content_stats']['pages']} pages, "
                f"{metadata['content_stats']['word_count']} words"
            )
            if metadata["features"]["has_timestamps"]:
                print(f"  ⏱️  {metadata['features']['timestamp_count']} timestamps")
            if metadata["features"]["has_bible_refs"]:
                print(f"  📖 {metadata['features']['bible_ref_count']} Bible references")
            print(f"  💾 {rel_metadata}")

        # Save summary
        print(f"\n{'=' * 70}")
        print("Saving extraction summary...")
        print(f"{'=' * 70}")

        summary = {
            "extraction_info": {
                "step": 1,
                "description": "Metadata extraction only - no chunking",
                "script": "extract_tbp_step1_metadata.py",
            },
            "extraction_stats": self.stats,
            "timestamp_stats": {
                "with_timestamps": self.stats["with_timestamps"],
                "without_timestamps": self.stats["extracted"] - self.stats["with_timestamps"],
            },
            "bible_reference_stats": {
                "with_bible_refs": self.stats["with_bible_refs"],
                "without_bible_refs": self.stats["extracted"] - self.stats["with_bible_refs"],
                "total_bible_references": self.stats["total_bible_refs"],
            },
            "by_category": self.category_stats,
            "by_type": self.type_stats,
            "failed_files": self.failed_files,
        }

        summary_file = self.extracted_dir / "extraction_summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"  ✓ Saved extraction_summary.json")

        # Print summary
        print(f"\n{'=' * 70}")
        print(f"📊 EXTRACTION SUMMARY")
        print(f"{'=' * 70}")
        print(f"Total PDFs found:       {self.stats['total_pdfs']}")
        print(f"Successfully extracted: {self.stats['extracted']}")
        print(f"Failed:                 {self.stats['failed']}")
        print(f"Total pages:            {self.stats['total_pages']}")
        print(f"With timestamps:        {self.stats['with_timestamps']}")
        print(f"With Bible refs:        {self.stats['with_bible_refs']}")
        print(f"Total Bible refs:       {self.stats['total_bible_refs']}")
        print(f"\nCategories: {len(self.category_stats)}")
        for cat, stats in sorted(self.category_stats.items()):
            print(
                f"  {cat}: {stats['count']} docs, {stats['pages']} pages, "
                f"{stats['bible_refs']} refs"
            )
        print(f"\nDocument Types: {len(self.type_stats)}")
        for dtype, stats in sorted(self.type_stats.items()):
            print(f"  {dtype}: {stats['count']} docs, {stats['bible_refs']} refs")
        print(f"{'=' * 70}")


def main():
    """Main execution."""
    # Vendored from the bible-study-assistant project for self-contained
    # re-derivation of BibleProject chunks. Paths adapted to bt-docker-mcp's
    # staging layout: this script lives at ingest/_tools/bibleproject/, so
    # walk up three levels to the repo root and point at ingest/_staging/.
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent

    tbp_dir = project_root / "ingest" / "_staging" / "bibleproject"

    print("=" * 70)
    print("BibleProject PDF Metadata Extractor - Step 1")
    print("=" * 70)
    print("Extracts metadata with NO chunking")
    print(f"Output: {tbp_dir / 'extracted'}/{{mirrored-structure}}/*.json")
    print("=" * 70)

    if not tbp_dir.exists():
        print(f"❌ Error: TBP directory not found at {tbp_dir}")
        return

    files_dir = tbp_dir / "files"
    if not files_dir.exists():
        print(f"❌ Error: Files directory not found at {files_dir}")
        return

    # Create extractor and process
    extractor = TBPMetadataExtractor(tbp_dir)
    extractor.process_pdfs()

    print(f"\n✅ Step 1 Metadata extraction complete!")
    print(f"📁 Output directory: {tbp_dir / 'extracted'}")
    print(f"\n📋 Next step: Run extract_tbp_step2_chunking.py")


if __name__ == "__main__":
    main()
