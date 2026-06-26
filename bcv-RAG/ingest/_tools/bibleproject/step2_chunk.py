#!/usr/bin/env python3
"""
BibleProject Intelligent Chunking - Step 2

Creates multiple chunking strategies from extracted metadata:
- Strategy A: Timestamp-based chunks (for video navigation)
- Strategy B: Bible reference-based chunks (for scripture search)
- Strategy C: Semantic chunks (for general search)

This is Step 2 of a two-step process:
  Step 1 (extract_tbp_step1_metadata.py): Extract metadata from PDFs
  Step 2 (this script): Create intelligent chunks for embedding

Reads from: imports/tbp/extracted/{folder}/{file}.json
Outputs to: imports/tbp/chunks/
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ChunkingStrategy:
    """Base class for chunking strategies."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.chunks_created = 0

    def create_chunks(self, metadata: Dict) -> List[Dict]:
        """Override in subclass."""
        raise NotImplementedError


class TimestampChunkingStrategy(ChunkingStrategy):
    """Chunk by video timestamps."""

    def __init__(self):
        super().__init__(
            "timestamp", "Chunks aligned with video timestamps for temporal navigation"
        )

    def create_chunks(self, metadata: Dict) -> List[Dict]:
        """Create chunks based on timestamp segments."""
        if not metadata["features"]["has_timestamps"]:
            return []

        chunks = []
        title = metadata["file_info"]["title"]
        full_text = metadata["full_text"]
        timestamps = metadata["timestamps"]

        # Sort timestamps by position
        sorted_timestamps = sorted(timestamps, key=lambda x: x["position"])

        # Build word position map
        words = full_text.split()
        char_to_word = {}
        char_pos = 0
        for word_idx, word in enumerate(words):
            char_to_word[char_pos] = word_idx
            char_pos += len(word) + 1  # +1 for space

        # Create chunks for each timestamp segment
        for idx, ts in enumerate(sorted_timestamps):
            # Find word position for this timestamp
            word_pos = char_to_word.get(ts["position"], 0)

            # Determine chunk boundaries
            if idx == 0:
                start_word = 0
            else:
                # Start from previous timestamp's position
                prev_pos = sorted_timestamps[idx - 1]["position"]
                start_word = char_to_word.get(prev_pos, 0)

            if idx < len(sorted_timestamps) - 1:
                next_pos = sorted_timestamps[idx + 1]["position"]
                end_word = char_to_word.get(next_pos, len(words))
            else:
                end_word = len(words)

            # Extract chunk text
            chunk_words = words[start_word:end_word]
            chunk_text = " ".join(chunk_words)

            # Add title prefix
            chunk_with_title = f"[{title}] {chunk_text}"

            # Find all Bible references in this chunk
            chunk_refs = []
            for ref in metadata["bible_references"]:
                ref_word_pos = char_to_word.get(ref["position"], -1)
                if start_word <= ref_word_pos < end_word:
                    chunk_refs.append(ref)

            chunk = {
                "text": chunk_with_title,
                "word_count": len(chunk_words),
                "timestamp_index": idx,
                "start_time": ts["start"],
                "end_time": ts["end"],
                "start_seconds": ts["start_seconds"],
                "end_seconds": ts["end_seconds"],
                "video_timestamp": ts["start_seconds"],
                "duration_seconds": ts["end_seconds"] - ts["start_seconds"],
                "bible_references": chunk_refs,
                "has_bible_refs": len(chunk_refs) > 0,
            }

            chunks.append(chunk)
            self.chunks_created += 1

        return chunks


class BibleReferenceChunkingStrategy(ChunkingStrategy):
    """Chunk by Bible reference density."""

    def __init__(self, max_words: int = 1200, min_words: int = 200):
        super().__init__(
            "bible_reference",
            "Chunks centered around Bible references for scripture-focused search",
        )
        self.max_words = max_words
        self.min_words = min_words

    def create_chunks(self, metadata: Dict) -> List[Dict]:
        """Create chunks based on Bible reference clusters."""
        if not metadata["features"]["has_bible_refs"]:
            return []

        chunks = []
        title = metadata["file_info"]["title"]
        full_text = metadata["full_text"]
        refs = metadata["bible_references"]

        if not refs:
            return []

        # Sort references by position
        sorted_refs = sorted(refs, key=lambda x: x["position"])

        # Build word position map
        words = full_text.split()
        char_to_word = {}
        char_pos = 0
        for word_idx, word in enumerate(words):
            char_to_word[char_pos] = word_idx
            char_pos += len(word) + 1

        # Group references into clusters
        ref_clusters = []
        current_cluster = [sorted_refs[0]]

        for ref in sorted_refs[1:]:
            prev_ref = current_cluster[-1]
            prev_word_pos = char_to_word.get(prev_ref["position"], 0)
            curr_word_pos = char_to_word.get(ref["position"], 0)

            # If references are within 100 words, keep in same cluster
            if curr_word_pos - prev_word_pos <= 100:
                current_cluster.append(ref)
            else:
                ref_clusters.append(current_cluster)
                current_cluster = [ref]

        if current_cluster:
            ref_clusters.append(current_cluster)

        # Create chunks for each cluster
        for cluster_idx, cluster in enumerate(ref_clusters):
            # Find center of cluster
            cluster_word_positions = [char_to_word.get(ref["position"], 0) for ref in cluster]
            center_word = sum(cluster_word_positions) // len(cluster_word_positions)

            # Determine chunk boundaries (centered on cluster)
            half_size = self.max_words // 2
            start_word = max(0, center_word - half_size)
            end_word = min(len(words), center_word + half_size)

            # Adjust to meet minimum size
            current_size = end_word - start_word
            if current_size < self.min_words:
                shortage = self.min_words - current_size
                # Try to expand equally on both sides
                expand_each = shortage // 2
                start_word = max(0, start_word - expand_each)
                end_word = min(len(words), end_word + expand_each)

            # Extract chunk text
            chunk_words = words[start_word:end_word]
            chunk_text = " ".join(chunk_words)
            chunk_with_title = f"[{title}] {chunk_text}"

            # Find primary reference (most specific in cluster)
            primary_ref = max(
                cluster, key=lambda r: (1 if "verse_start" in r else 0, r.get("verse_start", 0))
            )

            # Find timestamp if available
            chunk_timestamp = None
            for ts in metadata.get("timestamps", []):
                ts_word_pos = char_to_word.get(ts["position"], -1)
                if start_word <= ts_word_pos < end_word:
                    chunk_timestamp = ts
                    break

            chunk = {
                "text": chunk_with_title,
                "word_count": len(chunk_words),
                "reference_cluster_index": cluster_idx,
                "primary_reference": primary_ref["text"],
                "primary_book": primary_ref["book"],
                "primary_chapter": primary_ref.get("chapter"),
                "primary_verse": primary_ref.get("verse_start"),
                "all_references": [ref["text"] for ref in cluster],
                "reference_details": cluster,
                "has_timestamp": chunk_timestamp is not None,
            }

            if chunk_timestamp:
                chunk.update(
                    {
                        "start_time": chunk_timestamp["start"],
                        "end_time": chunk_timestamp["end"],
                        "start_seconds": chunk_timestamp["start_seconds"],
                        "end_seconds": chunk_timestamp["end_seconds"],
                        "video_timestamp": chunk_timestamp["start_seconds"],
                    }
                )

            chunks.append(chunk)
            self.chunks_created += 1

        return chunks


class SemanticChunkingStrategy(ChunkingStrategy):
    """Fixed-size semantic chunking with overlap."""

    def __init__(self, chunk_size: int = 800, overlap: int = 150):
        super().__init__("semantic", "Fixed-size chunks with overlap for general semantic search")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def create_chunks(self, metadata: Dict) -> List[Dict]:
        """Create fixed-size chunks with overlap."""
        chunks = []
        title = metadata["file_info"]["title"]
        full_text = metadata["full_text"]
        words = full_text.split()

        if len(words) == 0:
            return []

        # Build position maps
        char_to_word = {}
        char_pos = 0
        for word_idx, word in enumerate(words):
            char_to_word[char_pos] = word_idx
            char_pos += len(word) + 1

        i = 0
        chunk_idx = 0

        while i < len(words):
            # Extract chunk
            chunk_words = words[i : i + self.chunk_size]
            chunk_text = " ".join(chunk_words)
            chunk_with_title = f"[{title}] {chunk_text}"

            # Find Bible references in this chunk
            chunk_refs = []
            for ref in metadata["bible_references"]:
                ref_word_pos = char_to_word.get(ref["position"], -1)
                if i <= ref_word_pos < i + len(chunk_words):
                    chunk_refs.append(ref)

            # Find timestamps in this chunk
            chunk_timestamps = []
            for ts in metadata.get("timestamps", []):
                ts_word_pos = char_to_word.get(ts["position"], -1)
                if i <= ts_word_pos < i + len(chunk_words):
                    chunk_timestamps.append(ts)

            chunk = {
                "text": chunk_with_title,
                "word_count": len(chunk_words),
                "chunk_index": chunk_idx,
                "is_partial": i + self.chunk_size < len(words),
                "overlap_words": self.overlap if i + self.chunk_size < len(words) else 0,
                "bible_references": chunk_refs,
                "has_bible_refs": len(chunk_refs) > 0,
                "timestamps": chunk_timestamps,
                "has_timestamp": len(chunk_timestamps) > 0,
            }

            # Add timestamp range if available
            if chunk_timestamps:
                chunk["timestamp_range"] = [
                    chunk_timestamps[0]["start"],
                    chunk_timestamps[-1]["end"],
                ]
                chunk["start_seconds"] = chunk_timestamps[0]["start_seconds"]
                chunk["end_seconds"] = chunk_timestamps[-1]["end_seconds"]

            chunks.append(chunk)
            self.chunks_created += 1
            chunk_idx += 1

            # Move forward with overlap
            i += self.chunk_size - self.overlap

        return chunks


class TBPChunker:
    """Main chunking orchestrator."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.extracted_dir = base_path / "extracted"
        self.chunks_dir = base_path / "chunks"

        # Initialize strategies
        self.strategies = {
            "timestamp": TimestampChunkingStrategy(),
            "bible_reference": BibleReferenceChunkingStrategy(),
            "semantic": SemanticChunkingStrategy(),
        }

        # Statistics
        self.stats = {
            "total_files": 0,
            "processed": 0,
            "failed": 0,
            "by_strategy": {},
        }

    def process_all_files(self):
        """Process all metadata files and create chunks."""
        # Clean up old chunks directory
        if self.chunks_dir.exists():
            print(f"🗑️  Cleaning up old chunks directory...")
            import shutil

            shutil.rmtree(self.chunks_dir)

        # Create chunks directory structure
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        (self.chunks_dir / "by_strategy").mkdir(exist_ok=True)

        # Find all metadata JSON files
        json_files = sorted(self.extracted_dir.rglob("*.json"))
        # Exclude extraction_summary.json
        json_files = [f for f in json_files if f.name != "extraction_summary.json"]

        self.stats["total_files"] = len(json_files)

        print(f"\n🔍 Found {len(json_files)} metadata files")
        print(f"📁 Output: {self.chunks_dir}")
        print(f"\n{'=' * 70}")
        print("Starting multi-strategy chunking (Step 2)")
        print(f"{'=' * 70}")

        # Storage for all chunks by strategy
        all_chunks_by_strategy = {
            "timestamp": [],
            "bible_reference": [],
            "semantic": [],
        }

        chunk_id_counters = {
            "timestamp": 0,
            "bible_reference": 0,
            "semantic": 0,
        }

        # Process each file
        for json_path in json_files:
            rel_path = json_path.relative_to(self.extracted_dir)
            print(f"\n📄 {rel_path}")

            try:
                with open(json_path, "r") as f:
                    metadata = json.load(f)

                # Apply each strategy
                for strategy_name, strategy in self.strategies.items():
                    chunks = strategy.create_chunks(metadata)

                    if chunks:
                        # Add common metadata to each chunk
                        for chunk in chunks:
                            chunk_id = (
                                f"tbp_{strategy_name[:3]}_{chunk_id_counters[strategy_name]:05d}"
                            )
                            chunk_id_counters[strategy_name] += 1

                            chunk_with_metadata = {
                                "id": chunk_id,
                                "text": chunk["text"],
                                "strategy": strategy_name,
                                "metadata": {
                                    **chunk,
                                    "source": "bibleproject",
                                    "category": metadata["file_info"]["category"],
                                    "title": metadata["file_info"]["title"],
                                    "type": metadata["file_info"]["type"],
                                    "series": metadata["file_info"]["series"],
                                    "folder_path": metadata["file_info"]["folder_path"],
                                    "filename": metadata["file_info"]["filename"],
                                    "original_url": metadata["file_info"]["original_url"],
                                    "page_count": metadata["content_stats"]["pages"],
                                },
                            }
                            # Remove duplicate 'text' from metadata
                            del chunk_with_metadata["metadata"]["text"]

                            all_chunks_by_strategy[strategy_name].append(chunk_with_metadata)

                        print(f"  ✓ {strategy_name}: {len(chunks)} chunks")

                self.stats["processed"] += 1

            except Exception as e:
                print(f"  ✗ Error processing {json_path.name}: {e}")
                self.stats["failed"] += 1

        # Save strategy-specific files
        print(f"\n{'=' * 70}")
        print("Saving chunk files...")
        print(f"{'=' * 70}")

        for strategy_name, chunks in all_chunks_by_strategy.items():
            if chunks:
                strategy_file = self.chunks_dir / "by_strategy" / f"{strategy_name}_chunks.json"
                with open(strategy_file, "w") as f:
                    json.dump(chunks, f, indent=2)
                print(f"  ✓ {strategy_name}_chunks.json ({len(chunks)} chunks)")
                self.stats["by_strategy"][strategy_name] = len(chunks)

        # Create master file combining all strategies
        all_chunks = []
        master_id_counter = 0
        for strategy_name in ["timestamp", "bible_reference", "semantic"]:
            for chunk in all_chunks_by_strategy[strategy_name]:
                # Reassign master ID
                chunk_copy = chunk.copy()
                chunk_copy["id"] = f"tbp_{master_id_counter:05d}"
                chunk_copy["strategy_id"] = chunk["id"]  # Keep original strategy ID
                all_chunks.append(chunk_copy)
                master_id_counter += 1

        master_file = self.chunks_dir / "all_chunks_for_embedding.json"
        with open(master_file, "w") as f:
            json.dump(all_chunks, f, indent=2)
        print(f"  ✓ all_chunks_for_embedding.json ({len(all_chunks)} total chunks)")

        # Save summary
        summary = {
            "chunking_info": {
                "step": 2,
                "description": "Multi-strategy chunking from extracted metadata",
                "script": "extract_tbp_step2_chunking.py",
                "strategies": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "chunks_created": s.chunks_created,
                    }
                    for s in self.strategies.values()
                ],
            },
            "processing_stats": self.stats,
            "chunk_counts": {
                "by_strategy": self.stats["by_strategy"],
                "total_chunks": len(all_chunks),
            },
        }

        summary_file = self.chunks_dir / "chunking_summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"  ✓ chunking_summary.json")

        # Print final summary
        print(f"\n{'=' * 70}")
        print(f"📊 CHUNKING SUMMARY")
        print(f"{'=' * 70}")
        print(f"Files processed:      {self.stats['processed']}")
        print(f"Failed:               {self.stats['failed']}")
        print(f"\nChunks by Strategy:")
        for strategy_name, count in self.stats["by_strategy"].items():
            print(f"  {strategy_name:20s}: {count:4d} chunks")
        print(f"  {'TOTAL':20s}: {len(all_chunks):4d} chunks")
        print(f"{'=' * 70}")


def main():
    """Main execution."""
    # Vendored from the bible-study-assistant project. Paths adapted to
    # bt-docker-mcp's staging layout (see step1_extract.py for the same
    # rationale).
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent

    tbp_dir = project_root / "ingest" / "_staging" / "bibleproject"

    print("=" * 70)
    print("BibleProject Intelligent Chunking - Step 2")
    print("=" * 70)
    print("Strategies:")
    print("  A) Timestamp-based (video navigation)")
    print("  B) Bible reference-based (scripture search)")
    print("  C) Semantic fixed-size (general search)")
    print("=" * 70)

    if not tbp_dir.exists():
        print(f"❌ Error: TBP directory not found at {tbp_dir}")
        return

    extracted_dir = tbp_dir / "extracted"
    if not extracted_dir.exists():
        print(f"❌ Error: Extracted directory not found at {extracted_dir}")
        print("Run Step 1 (extract_tbp_step1_metadata.py) first!")
        return

    # Create chunker and process
    chunker = TBPChunker(tbp_dir)
    chunker.process_all_files()

    print(f"\n✅ Step 2 Chunking complete!")
    print(f"📁 Output directory: {tbp_dir / 'chunks'}")
    print(f"\n📋 Next: Generate embeddings and ingest to ChromaDB")


if __name__ == "__main__":
    main()
