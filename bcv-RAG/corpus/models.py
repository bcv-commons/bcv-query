from pydantic import BaseModel


class WordInfo(BaseModel):
    monad: int
    text: str
    trailer: str = ""
    lexeme: str = ""
    lexeme_utf8: str = ""
    gloss: str = ""
    part_of_speech: str = ""
    gender: str = ""
    number: str = ""
    person: str = ""
    state: str = ""
    verbal_stem: str = ""
    verbal_tense: str = ""
    language: str = ""


class VerseResult(BaseModel):
    book: str
    chapter: int
    verse: int
    words: list[WordInfo]


class PassageResult(BaseModel):
    corpus: str
    verses: list[VerseResult]


class BookInfo(BaseModel):
    name: str
    chapters: int


class FeatureInfo(BaseModel):
    name: str
    description: str = ""
    values: list[str] | None = None


class ObjectTypeInfo(BaseModel):
    name: str
    count: int
    features: list[FeatureInfo]


class SchemaResult(BaseModel):
    corpus: str
    object_types: list[ObjectTypeInfo]
