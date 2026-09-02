"""Generate PDF and DOCX versions of the sample resumes.

    python samples/make_samples.py

Useful for exercising the real PDF/DOCX extraction paths in the parser.
"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent


def to_pdf(text: str, out: pathlib.Path) -> None:
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    y, left, size, leading = 50, 50, 9.5, 12.5
    for line in text.split("\n"):
        if y > 780:
            page = doc.new_page()
            y = 50
        page.insert_text((left, y), line, fontsize=size, fontname="helv")
        y += leading
    doc.save(out)
    doc.close()


def to_docx(text: str, out: pathlib.Path) -> None:
    import docx

    document = docx.Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    document.save(out)


if __name__ == "__main__":
    for name in ("sample_resume", "strong_resume"):
        source = (HERE / f"{name}.txt").read_text(encoding="utf-8")
        to_pdf(source, HERE / f"{name}.pdf")
        to_docx(source, HERE / f"{name}.docx")
        print("wrote", f"{name}.pdf", "and", f"{name}.docx")
