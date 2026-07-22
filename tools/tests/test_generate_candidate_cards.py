from tools.generate_candidate_cards import parse_html_tables, stable_id


def test_stable_id_is_repeatable_and_input_sensitive() -> None:
    first = stable_id("中医内科学", "肺痨", "肺痨的基本病机是什么？")
    repeated = stable_id("中医内科学", "肺痨", "肺痨的基本病机是什么？")
    changed = stable_id("中医内科学", "肺痨", "肺痨的治则是什么？")

    assert first == repeated
    assert first != changed


def test_parse_html_tables_preserves_rows_and_cells() -> None:
    markdown = """
    <table>
      <tr><th>方名</th><th>功用</th></tr>
      <tr><td>桂枝汤</td><td>解肌发表，调和营卫</td></tr>
    </table>
    """

    assert parse_html_tables(markdown) == [[["方名", "功用"], ["桂枝汤", "解肌发表，调和营卫"]]]
