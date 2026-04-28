from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever
from devagent.core.structured_answers import answer_structured_question


def test_structured_record_answer_returns_exact_count_and_names(tmp_path: Path) -> None:
    backend = tmp_path / "backend" / "app" / "controllers"
    backend.mkdir(parents=True)
    catalogue_lines = []
    for index, name in enumerate(
        [
            "Alphonso Mangoes",
            "Bananas (Cavendish)",
            "Tomatoes Grade A",
            "Onions (Nashik)",
            "Potatoes (Jyoti)",
            "Cabbage Fresh",
            "Green Chilli Premium",
            "Farm Eggs (Tray)",
            "Paneer Blocks",
            "Frozen Peas",
            "Chicken Breast",
            "Sunflower Oil",
            "Basmati Rice",
            "Wheat Flour (Atta)",
            "Sugar (M-30 Grade)",
        ],
        start=1,
    ):
        catalogue_lines.append(
            "        {\n"
            f"            'product_id': 'PRD-{index:03d}',\n"
            f"            'name': '{name}',\n"
            "            'category': 'Groceries',\n"
            "        },\n"
        )
    (backend / "shop_controller.py").write_text(
        "def _seed_catalogue():\n"
        "    catalogue = [\n"
        + "".join(catalogue_lines)
        + "    ]\n"
        "    return catalogue\n",
        encoding="utf-8",
    )

    count_answer = answer_structured_question(
        tmp_path,
        "what is the total number of items which are listed in our shop?",
        intent="count",
    )
    list_answer = answer_structured_question(
        tmp_path,
        "can you list the names of those shop products?",
        intent="list",
    )

    assert count_answer is not None
    assert "**15**" in count_answer.answer
    assert "shop catalogue" in count_answer.answer.casefold()

    assert list_answer is not None
    for expected in ("Alphonso Mangoes", "Farm Eggs (Tray)", "Sugar (M-30 Grade)"):
        assert expected in list_answer.answer
    assert "1. Alphonso Mangoes" in list_answer.answer
    assert "15. Sugar (M-30 Grade)" in list_answer.answer


def test_dependency_manifest_answer_lists_direct_packages(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    backend = tmp_path / "backend"
    frontend.mkdir()
    backend.mkdir()
    (frontend / "package.json").write_text(
        '{"dependencies": {"react": "^19.0.0", "axios": "^1.7.0"}, "devDependencies": {"vite": "^5.4.0"}}',
        encoding="utf-8",
    )
    (backend / "requirements.txt").write_text("flask==3.1.0\npymongo==4.8.0\n", encoding="utf-8")

    answer = answer_structured_question(
        tmp_path,
        "What are the node packages required for this project?",
        intent="dependency",
    )

    assert answer is not None
    assert "`react`" in answer.answer
    assert "`axios`" in answer.answer
    assert "`vite`" in answer.answer
    assert "`flask`" not in answer.answer


def test_retriever_relaxes_file_diversity_for_list_intents(tmp_path: Path) -> None:
    lines = [f"product_{index} = 'Item {index}'" for index in range(1, 181)]
    (tmp_path / "catalogue.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    index = CodeIndexer(tmp_path, chunk_lines=40, overlap=0).build()
    results = Retriever(index).search_hybrid(["product catalogue item"], limit=4, intent="list")

    assert len(results) >= 2
    assert all(result.path == "catalogue.py" for result in results[:2])
