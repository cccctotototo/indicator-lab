import io

from quant_labeler.indicators import normalize_signal_csv


def test_signal_csv_direction_format():
    source = io.StringIO("timestamp,direction\n2026-01-01T00:00:00Z,long\n2026-01-01T01:00:00Z,short\n")
    result = normalize_signal_csv(source)
    assert result["long_signal"].tolist() == [True, False]
    assert result["short_signal"].tolist() == [False, True]
