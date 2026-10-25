"""Document search: indexing approved folders (as approved tasks) and searching the local index."""
import time

import pytest
from fastapi.testclient import TestClient

from app import docsearch
from app.main import create_app


@pytest.fixture
def docs(tmp_path, monkeypatch):
    root = tmp_path / "Documents"
    (root / "college").mkdir(parents=True)
    (root / "college" / "dbms.md").write_text("# DBMS\n\nNormalization removes redundancy. Third normal form (3NF) "
                                              "requires that non-key columns depend only on the key.", encoding="utf-8")
    (root / "trip.txt").write_text("Jaipur trip budget: train 900 rupees, hostel 600 per night.", encoding="utf-8")
    (root / "notes.bin").write_bytes(b"\x00\x01binary")  # unsupported type, ignored
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "passwords.txt").write_text("normalization hunter2", encoding="utf-8")
    monkeypatch.setenv("ATLAS_AGENT_FOLDERS", f"documents={root}")
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    return root


@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def run(api, **body):
    task = api.post("/api/tasks", json=body).json()
    assert task["state"] == "AwaitingApproval", task
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    for _ in range(300):
        done = api.get(f"/api/tasks/{task['id']}").json()
        if done["state"] in ("Succeeded", "Failed"):
            return done
        time.sleep(0.02)
    raise AssertionError(done)


def make_docx(path, paragraphs):
    import docx
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    d.save(str(path))


def make_pdf(path, text):
    # A minimal one-page PDF with a text object (no extra libraries needed).
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(out)


def test_indexing_needs_approval_and_then_search_finds_text_with_its_source(api, docs):
    assert api.get("/api/docs/search", params={"q": "normal form"}).json()["results"] == []
    task = api.post("/api/tasks", json={"kind": "index_documents", "folder": "documents"}).json()
    assert task["state"] == "AwaitingApproval" and "Reads the text" in task["action"]["risk"]
    assert docsearch.status()["files"] == 0  # nothing read before approval
    done = run(api, kind="index_documents", folder="documents")
    assert done["state"] == "Succeeded", done
    assert done["output"]["indexed"] == 2 and done["output"]["files"] == 2
    hits = api.get("/api/docs/search", params={"q": "what is third normal form"}).json()["results"]
    assert hits[0]["path"] == "college/dbms.md" and hits[0]["folder"] == "documents"
    assert "[normal]" in hits[0]["snippet"].lower() or "normal" in hits[0]["snippet"].lower()
    assert api.get("/api/docs/search", params={"q": "hunter2"}).json()["results"] == []  # outside folder never read


def test_pdf_and_word_files_are_indexed(api, docs):
    make_docx(docs / "resume.docx", ["Shashwat Mishra", "Skills: Python, FastAPI, SQL"])
    make_pdf(docs / "syllabus.pdf", "Operating systems deadlock and paging")
    run(api, kind="index_documents", folder="documents")
    assert api.get("/api/docs/search", params={"q": "FastAPI"}).json()["results"][0]["path"] == "resume.docx"
    assert api.get("/api/docs/search", params={"q": "deadlock"}).json()["results"][0]["path"] == "syllabus.pdf"


def test_reindex_skips_unchanged_updates_changed_and_drops_deleted_files(api, docs):
    run(api, kind="index_documents", folder="documents")
    (docs / "trip.txt").write_text("Goa trip instead: flight 4000 rupees.", encoding="utf-8")
    (docs / "college" / "dbms.md").unlink()
    out = run(api, kind="index_documents", folder="documents")["output"]
    assert (out["indexed"], out["unchanged"], out["removed"]) == (1, 0, 1)
    assert api.get("/api/docs/search", params={"q": "Jaipur"}).json()["results"] == []
    assert api.get("/api/docs/search", params={"q": "Goa"}).json()["results"][0]["path"] == "trip.txt"
    out = run(api, kind="index_documents", folder="documents")["output"]
    assert out["unchanged"] == 1 and out["indexed"] == 0


def test_damaged_files_are_reported_not_fatal(api, docs):
    (docs / "broken.pdf").write_bytes(b"%PDF-1.4 not really")
    out = run(api, kind="index_documents", folder="documents")["output"]
    assert out["failed"] == 1 and out["indexed"] == 2 and out["unreadable"] == 1


def test_symlinked_files_and_folders_are_not_indexed(api, docs, tmp_path):
    try:
        (docs / "link-out").symlink_to(tmp_path / "secret", target_is_directory=True)
        (docs / "link-file.txt").symlink_to(tmp_path / "secret" / "passwords.txt")
    except OSError:
        pytest.skip("symlinks not available")
    run(api, kind="index_documents", folder="documents")
    assert api.get("/api/docs/search", params={"q": "hunter2"}).json()["results"] == []


def test_search_input_cannot_break_the_query(api, docs):
    run(api, kind="index_documents", folder="documents")
    for q in ['"', "NEAR(", "a OR", "*", "dbms) OR (x", "^col:"]:
        assert api.get("/api/docs/search", params={"q": q}).status_code == 200


def test_clearing_the_index_needs_confirmation(api, docs):
    run(api, kind="index_documents", folder="documents")
    assert api.post("/api/docs/clear", json={}).status_code == 400
    assert api.post("/api/docs/clear", json={"confirm": True}).json()["removed_files"] == 2
    assert api.get("/api/docs/status").json()["files"] == 0


def test_chunks_split_long_text_with_overlap():
    text = " ".join(f"Sentence number {i}." for i in range(400))
    pieces = docsearch.chunks_of(text)
    assert len(pieces) > 3 and all(len(p) <= docsearch.CHUNK_CHARS for p in pieces)
    assert pieces[0][-20:] in pieces[1] or pieces[1][:20] in pieces[0]
