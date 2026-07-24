from quant_labeler.indicators import inspect_pine


def test_inspect_pine_reports_pinets_engine(tmp_path):
    source = tmp_path / "sample.pine"
    source.write_text(
        '//@version=6\nindicator("Sample title", overlay=true)\n',
        encoding="utf-8",
    )

    result = inspect_pine(source)

    assert result.stem == "sample"
    assert result.title == "Sample title"
    assert result.version == "6"
    assert result.engine == "PineTS"
