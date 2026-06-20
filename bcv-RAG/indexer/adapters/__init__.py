"""Source-format adapters. Each adapter turns one file into a Document."""

from .base import Adapter, Document
from .markdown import MarkdownAdapter

__all__ = ["Adapter", "Document", "MarkdownAdapter"]
