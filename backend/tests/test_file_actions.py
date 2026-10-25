"""Write actions: new files only, Word/Excel creation, ATLAS trash with restore, media keys."""
import platform
import time

import pytest
from fastapi.testclient import TestClient

from app import agent
from app.main import create_app


@pytest.fixture
def docs(tmp_path, monkeypatch):
    root = tmp_path / "Documents"
    (root / "notes").mkdir(parents=True)
    (root / "old.txt").write_text("keep me", encoding="utf-8")
    monkeypatch.setenv("ATLAS_AGENT_FOLDERS", f"documents={root}")
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    return root


@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def create(api, **body):
    return api.post("/api/tasks", json=body)


def run(api, **body):
    r = create(api, **body)
    assert r.status_code == 202, r.text
    task = r.json()
    assert task["state"] == "AwaitingApproval"
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    for _ in range(300):
        done = api.get(f"/api/tasks/{task['id']}").json()
        if done["state"] in ("Succeeded", "Failed"):
            return done
        time.sleep(0.02)
    raise AssertionError(done)


def test_create_note_writes_a_new_file_after_approval(api, docs):
    r = create(api, kind="create_note", folder="documents", path="notes", name="exam plan", text="Day 1: DBMS")
    task = r.json()
    assert "Create 'exam plan'" in task["action"]["summary"] and "Never overwrites" in task["action"]["risk"]
    assert not (docs / "notes" / "exam plan.txt").exists()  # nothing written before approval
    done = run(api, kind="create_note", folder="documents", path="notes", name="exam plan", text="Day 1: DBMS")
    assert done["state"] == "Succeeded", done
    assert done["output"]["created"] == "notes/exam plan.txt"
    assert (docs / "notes" / "exam plan.txt").read_text(encoding="utf-8") == "Day 1: DBMS"


def test_markdown_notes_keep_their_extension(api, docs):
    run(api, kind="create_note", folder="documents", name="todo.md", text="- one")
    assert (docs / "todo.md").read_text(encoding="utf-8") == "- one"


def test_existing_files_are_never_overwritten(api, docs):
    r = create(api, kind="create_note", folder="documents", name="old", text="replaced")
    assert r.status_code == 409 and r.json()["code"] == "file_exists"
    # A file that appears after approval is not overwritten either.
    task = create(api, kind="create_note", folder="documents", name="race", text="from atlas").json()
    (docs / "race.txt").write_text("user's own file", encoding="utf-8")
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    time.sleep(0.5)
    assert api.get(f"/api/tasks/{task['id']}").json()["state"] == "Failed"
    assert (docs / "race.txt").read_text(encoding="utf-8") == "user's own file"
    assert (docs / "old.txt").read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize("name", ["../escape", "a/b", ".env", "x" * 101, "bad:name", "con|pipe", ""])
def test_bad_file_names_are_refused(api, docs, name):
    assert create(api, kind="create_note", folder="documents", name=name, text="x").status_code == 422


def test_approval_is_bound_to_the_exact_text(api, docs):
    a = create(api, kind="create_note", folder="documents", name="a", text="one").json()
    b = create(api, kind="create_note", folder="documents", name="b", text="two").json()
    assert a["approval_hash"] != b["approval_hash"]
    assert api.post(f"/api/tasks/{a['id']}/approve", json={"approval_hash": b["approval_hash"]}).status_code == 409


def test_word_document_has_title_headings_and_bullets(api, docs):
    done = run(api, kind="create_document", folder="documents", name="Study plan", format="docx", title="Semester 5",
               text="# Week 1\n- DBMS normalization\n- OS paging\nRevise daily.")
    assert done["state"] == "Succeeded", done
    import docx
    d = docx.Document(str(docs / "Study plan.docx"))
    texts = [(p.style.name, p.text) for p in d.paragraphs]
    assert ("Title", "Semester 5") in texts and ("Heading 1", "Week 1") in texts
    assert ("List Bullet", "DBMS normalization") in texts and ("Normal", "Revise daily.") in texts


def test_excel_cells_are_text_so_formulas_cannot_run(api, docs):
    done = run(api, kind="create_document", folder="documents", name="budget", format="xlsx", title="Trip",
               text='item,cost\ntrain,900\nevil,"=HYPERLINK(""http://x"",""y"")"')
    assert done["state"] == "Succeeded", done
    from openpyxl import load_workbook
    sheet = load_workbook(str(docs / "budget.xlsx")).active
    assert sheet.title == "Trip" and sheet["A2"].value == "train"
    assert sheet["B3"].value.startswith("=HYPERLINK") and sheet["B3"].data_type == "s"


def test_trash_moves_a_file_out_and_restore_puts_it_back(api, docs):
    done = run(api, kind="move_to_trash", folder="documents", path="old.txt")
    assert done["state"] == "Succeeded", done
    assert not (docs / "old.txt").exists()
    items = api.get("/api/desktop/trash").json()["items"]
    assert items[0]["path"] == "old.txt" and items[0]["folder"] == "documents"
    restored = run(api, kind="restore_from_trash", trash_id=items[0]["id"])
    assert restored["state"] == "Succeeded", restored
    assert (docs / "old.txt").read_text(encoding="utf-8") == "keep me"
    assert api.get("/api/desktop/trash").json()["items"] == []


def test_restore_never_overwrites_a_new_file_with_the_same_name(api, docs):
    run(api, kind="move_to_trash", folder="documents", path="old.txt")
    (docs / "old.txt").write_text("new version", encoding="utf-8")
    item = api.get("/api/desktop/trash").json()["items"][0]
    assert run(api, kind="restore_from_trash", trash_id=item["id"])["state"] == "Failed"
    assert (docs / "old.txt").read_text(encoding="utf-8") == "new version"


@pytest.mark.parametrize("path", ["notes", "../x.txt", "missing.txt"], ids=["folder", "outside", "missing"])
def test_trash_only_takes_regular_files_inside_the_folder(api, docs, path):
    r = create(api, kind="move_to_trash", folder="documents", path=path)
    if r.status_code == 202:
        task = r.json()
        api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
        time.sleep(0.4)
        assert api.get(f"/api/tasks/{task['id']}").json()["state"] == "Failed"
    else:
        assert r.status_code == 422
    assert (docs / "notes").is_dir()


def test_trash_moves_a_link_itself_never_its_target(api, docs, tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    try:
        (docs / "link.txt").symlink_to(target)
    except OSError:
        pytest.skip("symlinks not available")
    r = create(api, kind="move_to_trash", folder="documents", path="link.txt")
    assert r.status_code == 422 and r.json()["code"] == "outside_folder"  # refused before approval
    assert (docs / "link.txt").is_symlink() and target.read_text(encoding="utf-8") == "outside"


def test_unknown_trash_ids_are_refused(api, docs):
    assert create(api, kind="restore_from_trash", trash_id="0123456789ab").status_code == 404
    assert create(api, kind="restore_from_trash", trash_id="../../etc").status_code == 422


def test_media_keys_are_typed_and_windows_only(api, docs):
    assert create(api, kind="media_key", key="format_c").status_code == 422
    done = run(api, kind="media_key", key="play_pause")
    if platform.system() == "Windows":
        assert done["state"] == "Succeeded"
    else:
        assert done["state"] == "Failed" and done["error"]["code"] == "unsupported_os"


def test_write_actions_need_the_agent_switched_on(api, docs, monkeypatch):
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "false")
    assert create(api, kind="create_note", folder="documents", name="x", text="y").status_code == 403
    assert agent.list_trash() == []
