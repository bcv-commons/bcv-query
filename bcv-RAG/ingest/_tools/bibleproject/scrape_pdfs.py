#!/usr/bin/env python3
"""
BibleProject PDF Scraper - Mirror CloudFront Folder Structure

Downloads PDFs from BibleProject and mirrors their CloudFront folder structure:
- Script References/
- Study Notes/
- Insight Videos/
- The Wilderness/
- etc.

This preserves the original organization for better categorization.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup


class BibleProjectScraper:
    """Scraper that mirrors CloudFront folder structure."""

    BASE_URL = "https://bibleproject.com/downloads/"
    CLOUDFRONT_PATTERN = r'href="(https://d1bsmz3sdihplr\.cloudfront\.net/[^"]*\.pdf)"'
    HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    def __init__(
        self,
        output_dir: str = "ingest/_staging/bibleproject",
        config_path: str = "ingest/_tools/bibleproject/tbp.json",
        delay: float = 0.5,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir = self.output_dir / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir = self.output_dir / "metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.delay = delay
        self.downloaded: Set[str] = set()
        self.failed: List[Dict] = []
        self.md5_hashes: Dict[str, str] = {}
        self.stats = {"downloaded": 0, "skipped": 0, "duplicates": 0, "failed": 0, "redirected": 0}

    def _load_config(self) -> Dict:
        """Load configuration file with path redirections."""
        if not self.config_path.exists():
            print(f"⚠️  Config not found: {self.config_path}, using defaults")
            return {"path_redirections": []}

        try:
            with open(self.config_path) as f:
                config = json.load(f)
                print(f"✅ Loaded config: {config.get('name', 'Unknown')}")
                enabled_redirections = [
                    r for r in config.get("path_redirections", []) if r.get("enabled", True)
                ]
                print(f"   {len(enabled_redirections)} path redirection rules active")
                return config
        except Exception as e:
            print(f"⚠️  Failed to load config: {e}, using defaults")
            return {"path_redirections": []}

    def apply_path_redirections(self, folder_path: str) -> Optional[str]:
        """Apply path redirection rules from config."""
        redirections = self.config.get("path_redirections", [])

        for rule in redirections:
            if not rule.get("enabled", True):
                continue

            pattern = rule.get("pattern")
            target = rule.get("target")

            if not pattern or not target:
                continue

            match = re.match(pattern, folder_path)
            if match:
                # Replace capture groups in target
                redirected = target
                for i, group in enumerate(match.groups(), 1):
                    redirected = redirected.replace(f"${i}", group)

                print(f"   🔀 Redirected: {folder_path} → {redirected}")
                return redirected

        return None

    def sanitize_path_component(self, name: str) -> str:
        """Sanitize a single path component (folder or filename)."""
        # Remove or replace problematic characters
        name = re.sub(r'[<>:"|?*]', "", name)
        name = name.replace("/", "-")
        name = name.replace("\\", "-")
        # Replace spaces with dashes
        name = name.replace(" ", "-")
        # Replace multiple dashes with single dash
        name = re.sub(r"-+", "-", name)
        # Remove leading/trailing dashes
        name = name.strip("-")
        # Limit length
        return name[:150]

    def extract_pdf_urls(self) -> List[Dict[str, str]]:
        """Extract all PDF URLs from the downloads page."""
        print(f"📡 Fetching {self.BASE_URL}...")

        try:
            response = self.session.get(self.BASE_URL, timeout=30)
            response.raise_for_status()
        except Exception as e:
            print(f"❌ Failed to fetch page: {e}")
            return []

        # Extract all CloudFront PDF URLs
        pdf_urls = re.findall(self.CLOUDFRONT_PATTERN, response.text)
        print(f"✅ Found {len(pdf_urls)} PDF URLs\n")

        resources = []
        for url in pdf_urls:
            decoded_url = unquote(url)

            # Extract path after /media/
            parts = decoded_url.split("/media/")
            if len(parts) < 2:
                continue

            media_path = parts[1]
            path_parts = media_path.split("/")

            # Get filename (last part)
            filename = path_parts[-1]

            # Get folder path (everything except filename)
            folders = path_parts[:-1]

            resources.append(
                {
                    "url": url,
                    "decoded_url": decoded_url,
                    "filename": filename,
                    "folders": folders,
                    "folder_path": "/".join(folders),
                }
            )

        return resources

    def compute_md5(self, filepath: Path) -> str:
        """Compute MD5 hash of a file."""
        import hashlib

        md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5.update(chunk)
        return md5.hexdigest()

    def download_file(self, url: str, filepath: Path, description: str = "") -> bool:
        """Download a single file with validation."""
        if filepath.exists():
            size_kb = filepath.stat().st_size // 1024
            print(f"  ⏭  Already exists: {filepath.name} ({size_kb} KB)")
            self.stats["skipped"] += 1
            return True

        try:
            print(f"  ⬇  Downloading: {description or filepath.name}")
            response = self.session.get(url, timeout=30, stream=True, allow_redirects=True)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get("content-type", "")
            if "pdf" not in content_type.lower():
                print(f"  ⚠  Not a PDF: {content_type}")
                self.failed.append({"url": url, "error": f"Not a PDF: {content_type}"})
                self.stats["failed"] += 1
                return False

            # Write file
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Compute MD5 hash
            file_hash = self.compute_md5(filepath)

            # Check for duplicates
            if file_hash in self.md5_hashes:
                original = self.md5_hashes[file_hash]
                print(f"  ⚠  DUPLICATE of {original}")
                os.remove(filepath)
                self.stats["duplicates"] += 1
                return False

            self.md5_hashes[file_hash] = str(filepath.relative_to(self.files_dir))

            size_kb = filepath.stat().st_size // 1024
            self.downloaded.add(str(filepath))
            self.stats["downloaded"] += 1
            print(f"  ✓  Downloaded: {filepath.name} ({size_kb} KB)")

            time.sleep(self.delay)
            return True

        except Exception as e:
            print(f"  ✗  Failed: {e}")
            self.failed.append({"url": url, "error": str(e), "description": description})
            self.stats["failed"] += 1
            return False

    def download_resource(self, resource: Dict) -> None:
        """Download a single resource into mirrored folder structure with redirections."""
        url = resource["url"]
        filename = resource["filename"]
        folders = resource["folders"]

        # Sanitize folder names
        sanitized_folders = [self.sanitize_path_component(f) for f in folders]

        # Construct original path
        original_path = "/".join(sanitized_folders) if sanitized_folders else ""

        # Apply path redirections
        redirected_path = self.apply_path_redirections(original_path)

        if redirected_path:
            self.stats["redirected"] += 1
            # Use redirected path
            path_parts = redirected_path.split("/")
            sanitized_folders = path_parts
            target_dir = self.files_dir / Path(*path_parts)
        else:
            # Use original path
            if sanitized_folders:
                target_dir = self.files_dir / Path(*sanitized_folders)
            else:
                target_dir = self.files_dir / "Root"

        target_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        sanitized_filename = self.sanitize_path_component(filename)
        filepath = target_dir / sanitized_filename

        # Display path
        display_path = (
            "/".join(list(target_dir.relative_to(self.output_dir).parts) + [sanitized_filename])
            if target_dir != self.output_dir
            else sanitized_filename
        )

        print(f"📄 {display_path}")
        self.download_file(url, filepath, filename)

    def save_manifest(self, all_resources: List[Dict]) -> None:
        """Save manifest with download results."""
        manifest_path = self.metadata_dir / "download-manifest.json"

        # Enhance resources with sanitized paths
        enhanced_resources = []
        for resource in all_resources:
            sanitized_folders = [self.sanitize_path_component(f) for f in resource["folders"]]
            sanitized_filename = self.sanitize_path_component(resource["filename"])

            enhanced_resources.append(
                {
                    "url": resource["url"],
                    "original_path": resource["decoded_url"],
                    "filename": resource["filename"],
                    "sanitized_filename": sanitized_filename,
                    "folders": resource["folders"],
                    "sanitized_folders": sanitized_folders,
                    "folder_path": resource["folder_path"],
                    "sanitized_path": "/".join(sanitized_folders) if sanitized_folders else "",
                }
            )

        manifest = {
            "source": self.BASE_URL,
            "total_discovered": len(all_resources),
            "stats": self.stats,
            "resources": enhanced_resources,
            "failed": self.failed,
            "md5_hashes": {path: hash_val for hash_val, path in self.md5_hashes.items()},
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f"\n📄 Manifest saved to: {manifest_path}")

    def run(self) -> None:
        """Run the complete scraping process."""
        print("=" * 70)
        print("📚 BibleProject PDF Scraper (Mirrored Structure + Config)")
        print("=" * 70)
        print(f"Output directory: {self.output_dir.absolute()}")
        print(f"Files directory: {self.files_dir.absolute()}")
        print(f"Metadata directory: {self.metadata_dir.absolute()}")
        print(f"Config file: {self.config_path.absolute()}")
        print(f"Rate limit delay: {self.delay}s between downloads")
        print()

        # Extract PDF URLs from page
        all_resources = self.extract_pdf_urls()

        if not all_resources:
            print("❌ No resources found!")
            return

        # Analyze folder structure
        folders_count = {}
        for resource in all_resources:
            if resource["folders"]:
                primary = resource["folders"][0]
                folders_count[primary] = folders_count.get(primary, 0) + 1

        print(f"📊 Found {len(all_resources)} total PDFs")
        print(f"📂 Primary folder distribution:")
        for folder, count in sorted(folders_count.items(), key=lambda x: -x[1])[:10]:
            print(f"   {count:3d}  {folder}")
        print()

        # Download all resources
        print("=" * 70)
        print("📥 Starting downloads...")
        print("=" * 70)
        print()

        for resource in all_resources:
            self.download_resource(resource)

        # Save manifest
        self.save_manifest(all_resources)

        # Print summary
        print("\n" + "=" * 70)
        print("=" * 70)
        print("📊 SUMMARY")
        print("=" * 70)
        print(f"✅ Successfully downloaded: {self.stats['downloaded']} files")
        print(f"🔀 Path redirections applied: {self.stats['redirected']}")
        print(f"⏭  Skipped (already exist): {self.stats['skipped']}")
        print(f"⚠️  Duplicates detected: {self.stats['duplicates']}")
        print(f"❌ Failed downloads: {self.stats['failed']}")

        if self.failed:
            print(f"\n⚠️  Failed Downloads (first 10):")
            for failure in self.failed[:10]:
                desc = failure.get("description", failure.get("url", "Unknown"))
                error = failure.get("error", "Unknown error")
                print(f"   ✗ {desc}")
                print(f"      {error[:80]}")

        print(f"\n📁 All files saved to: {self.files_dir.absolute()}")
        print(f"📄 Manifest saved to: {self.metadata_dir / 'download-manifest.json'}")

        # Show directory structure
        print("\n" + "=" * 70)
        print("📁 DIRECTORY STRUCTURE")
        print("=" * 70)
        print("Directory tree preview:")
        self.show_directory_structure()

    def show_directory_structure(self, max_depth: int = 2) -> None:
        """Show a preview of the directory structure."""

        def walk_dir(path: Path, prefix: str = "", depth: int = 0):
            if depth >= max_depth:
                return

            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            dirs = [
                x
                for x in items
                if x.is_dir()
                and not x.name.startswith(".")
                and not x.name in ["metadata", "config", "extracted"]
            ]
            files = [x for x in items if x.is_file() and x.suffix == ".pdf"]

            # Show directories
            for i, d in enumerate(dirs[:5]):  # Limit to first 5
                is_last = (i == len(dirs) - 1) and not files
                connector = "└── " if is_last else "├── "
                print(f"{prefix}{connector}{d.name}/")

                new_prefix = prefix + ("    " if is_last else "│   ")
                walk_dir(d, new_prefix, depth + 1)

            if len(dirs) > 5:
                print(f"{prefix}... and {len(dirs) - 5} more directories")

            # Show files (just count)
            if files:
                if len(files) <= 3:
                    for f in files:
                        print(f"{prefix}├── {f.name}")
                else:
                    print(f"{prefix}├── {files[0].name}")
                    print(f"{prefix}├── ... {len(files) - 2} more files")
                    print(f"{prefix}└── {files[-1].name}")

        walk_dir(self.output_dir)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Download BibleProject PDFs with mirrored folder structure"
    )
    parser.add_argument(
        "--output", "-o", default="ingest/_staging/bibleproject",
        help="Output directory (default: ingest/_staging/bibleproject)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="ingest/_tools/bibleproject/tbp.json",
        help="Config file path (default: ingest/_tools/bibleproject/tbp.json)",
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=0.5,
        help="Delay between downloads in seconds (default: 0.5)",
    )

    args = parser.parse_args()

    scraper = BibleProjectScraper()
        output_dir=args.output, config_path=args.config, delay=args.delay
    )
    scraper.run()


if __name__ == "__main__":
    main()
