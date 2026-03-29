from docmancer.connectors.parsers.text import TextLoader
from docmancer.connectors.parsers.markdown import MarkdownLoader

def test_text_loader(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello world")
    doc = TextLoader().load(f)
    assert doc.content == "Hello world"
    assert ".txt" in TextLoader.supported_extensions

def test_markdown_loader(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("# Title\nContent")
    doc = MarkdownLoader().load(f)
    assert "Title" in doc.content
    assert ".md" in MarkdownLoader.supported_extensions
