"""Readers on small hand-written inputs.

The inputs use real column codes of the spec but made-up cell values. Messages are
checked for the absence of cell values.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from spot_report.ingest import (
    ReadError,
    load_bundle,
    read_csv_responses,
    read_responses,
    read_xlsx_responses,
    unconverted_columns,
)
from spot_report.ingest.manifest import ManifestError
from spot_report.questionnaire import QuestionnaireSpec, load_spec

STRING = pd.StringDtype(na_value=pd.NA)
HEADER = "id,submitdate,DQSEX,DQAGE,PHQ9[PHQQ1],DIAGQ1[DEPR],DIAGQ1[other]"


@pytest.fixture(scope="module")
def spec() -> QuestionnaireSpec:
    return load_spec("2026.1")


def write_csv(tmp_path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    path = tmp_path / "responses.csv"
    path.write_bytes(text.encode(encoding))
    return path


def write_xlsx(tmp_path: Path, rows: list[list[object]]) -> Path:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    path = tmp_path / "responses.xlsx"
    workbook.save(path)
    return path


# --- CSV -----------------------------------------------------------------------------


def test_csv_types_and_values(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_csv(
        tmp_path,
        f"{HEADER}\n10,2025-08-22,W,15,2,Y,\n11,2025-08-22,M,16,0,,\n",
    )
    df = read_csv_responses(path, spec)
    assert list(df.columns) == HEADER.split(",")
    assert df["id"].dtype == pd.Int64Dtype()
    assert df["DQAGE"].dtype == pd.Int64Dtype()
    assert df["PHQ9[PHQQ1]"].dtype == pd.Int64Dtype()
    for code in ("submitdate", "DQSEX", "DIAGQ1[DEPR]", "DIAGQ1[other]"):
        assert df[code].dtype == STRING
    assert df["id"].tolist() == [10, 11]
    assert df["DQAGE"].tolist() == [15, 16]
    assert df["submitdate"].tolist() == ["2025-08-22", "2025-08-22"]
    assert df["DIAGQ1[DEPR]"].isna().tolist() == [False, True]
    assert df["DIAGQ1[other]"].isna().all()
    assert isinstance(df.index, pd.RangeIndex)


def test_csv_with_bom_and_crlf(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_csv(tmp_path, f"﻿{HEADER}\r\n1,2025-08-22,M,15,1,,\r\n")
    df = read_csv_responses(path, spec)
    assert df.columns[0] == "id"
    assert df["id"].tolist() == [1]
    assert df["DQSEX"].tolist() == ["M"]


def test_csv_strips_headings_and_cells(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_csv(
        tmp_path,
        " id , DQSEX ,DQAGE\n 1 ,  W ,\t15 \n",
    )
    df = read_csv_responses(path, spec)
    assert list(df.columns) == ["id", "DQSEX", "DQAGE"]
    assert df["DQSEX"].tolist() == ["W"]
    assert df["DQAGE"].tolist() == [15]


def test_csv_empty_and_whitespace_cells_become_na(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(tmp_path, "id,DQSEX,DQAGE\n1,,15\n2,   ,\n3,M,16\n")
    df = read_csv_responses(path, spec)
    assert df["DQSEX"].isna().tolist() == [True, True, False]
    assert df["DQAGE"].isna().tolist() == [False, True, False]
    assert df["DQAGE"].dtype == pd.Int64Dtype()


def test_na_like_text_is_kept_as_text(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_csv(tmp_path, "id,DQSEX\n1,NA\n2,null\n3,N/A\n")
    df = read_csv_responses(path, spec)
    assert df["DQSEX"].tolist() == ["NA", "null", "N/A"]


def test_blank_lines_and_empty_rows_are_dropped(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(tmp_path, "id,DQSEX,DQAGE\n1,M,15\n\n, ,\n2,W,16\n")
    df = read_csv_responses(path, spec)
    assert df["id"].tolist() == [1, 2]
    assert isinstance(df.index, pd.RangeIndex)
    assert df.index.tolist() == [0, 1]


def test_csv_quoted_field_with_delimiter(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(tmp_path, 'id,DIAGQ1[other]\n1,"a, b"\n2,"say ""x"""\n')
    df = read_csv_responses(path, spec)
    assert df["DIAGQ1[other]"].dtype == STRING
    assert df["DIAGQ1[other]"].tolist() == ["a, b", 'say "x"']


def test_free_text_is_kept_as_string_even_if_numeric(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(tmp_path, "id,DIAGQ1[other]\n1,42\n")
    df = read_csv_responses(path, spec)
    assert df["DIAGQ1[other]"].dtype == STRING
    assert df["DIAGQ1[other]"].tolist() == ["42"]


def test_columns_unknown_to_the_spec_become_strings(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(tmp_path, "id,SOMETHING\n1,5\n")
    df = read_csv_responses(path, spec)
    assert df["SOMETHING"].dtype == STRING
    assert df["SOMETHING"].tolist() == ["5"]


def test_header_only_file_gives_empty_typed_frame(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    df = read_csv_responses(write_csv(tmp_path, "id,DQAGE,DQSEX\n"), spec)
    assert len(df) == 0
    assert df["id"].dtype == pd.Int64Dtype()
    assert df["DQAGE"].dtype == pd.Int64Dtype()
    assert df["DQSEX"].dtype == STRING


def test_non_numbers_are_not_turned_into_na(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(
        tmp_path, "id,DQAGE,PHQ9[PHQQ1],PHQ9[PHQQ2]\n1,15,x,2\n2,fifteen,1,3\n"
    )
    df = read_csv_responses(path, spec)
    assert df["DQAGE"].dtype == STRING
    assert df["DQAGE"].tolist() == ["15", "fifteen"]
    assert df["PHQ9[PHQQ1]"].dtype == STRING
    assert df["PHQ9[PHQQ1]"].tolist() == ["x", "1"]
    assert df["PHQ9[PHQQ2]"].dtype == pd.Int64Dtype()
    assert unconverted_columns(df, spec) == ("DQAGE", "PHQ9[PHQQ1]")


@pytest.mark.parametrize("bad", ["2.5", "3.0", "1e2", "--1", "1 2", "٣"])
def test_non_integer_numeric_text_stays_raw(
    tmp_path: Path, spec: QuestionnaireSpec, bad: str
) -> None:
    path = write_csv(tmp_path, f"id,DQAGE\n1,15\n2,{bad}\n")
    df = read_csv_responses(path, spec)
    assert df["DQAGE"].dtype == STRING
    assert df["DQAGE"].tolist() == ["15", bad]


def test_signed_and_padded_integers(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_csv(tmp_path, "id,DQAGE\n1,+5\n2,007\n3,-1\n")
    df = read_csv_responses(path, spec)
    assert df["DQAGE"].tolist() == [5, 7, -1]


def test_huge_integer_stays_raw(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_csv(tmp_path, f"id,DQAGE\n1,{'9' * 40}\n")
    df = read_csv_responses(path, spec)
    assert df["DQAGE"].dtype == STRING


def test_non_integer_id_is_reported_as_unconverted(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    df = read_csv_responses(write_csv(tmp_path, "id,DQSEX\nabc,M\n"), spec)
    assert unconverted_columns(df, spec) == ("id",)


def test_unconverted_columns_empty_for_clean_data(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    df = read_csv_responses(write_csv(tmp_path, "id,DQAGE\n1,15\n"), spec)
    assert unconverted_columns(df, spec) == ()


# --- CSV errors ----------------------------------------------------------------------


def test_missing_file(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    with pytest.raises(ReadError, match=r"nothing\.csv: file not found"):
        read_csv_responses(tmp_path / "nothing.csv", spec)


def test_empty_file(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    with pytest.raises(ReadError, match="no heading row"):
        read_csv_responses(write_csv(tmp_path, ""), spec)


def test_not_utf8(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_csv(tmp_path, "id,DQSEX\n1,Schüler\n", encoding="latin-1")
    with pytest.raises(ReadError, match="not valid UTF-8"):
        read_csv_responses(path, spec)


def test_wrong_delimiter(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    with pytest.raises(ReadError, match="delimiter"):
        read_csv_responses(write_csv(tmp_path, "id;DQSEX\n1;M\n"), spec)


def test_ragged_row_reports_line_not_values(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(tmp_path, "id,DQSEX\n1,M\n2,SECRETVALUE,extra\n")
    with pytest.raises(ReadError, match="line 3 has 3 fields, expected 2") as info:
        read_csv_responses(path, spec)
    assert "SECRETVALUE" not in str(info.value)


def test_duplicate_headings(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    with pytest.raises(ReadError, match=r"duplicate headings in columns \[3\]"):
        read_csv_responses(write_csv(tmp_path, "id,DQSEX,id\n1,M,2\n"), spec)


def test_headingless_column_with_cells(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    with pytest.raises(ReadError, match="column 3 has cells but no heading"):
        read_csv_responses(write_csv(tmp_path, "id,DQSEX,\n1,M,x\n"), spec)


def test_headingless_empty_column_is_dropped(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    df = read_csv_responses(write_csv(tmp_path, "id,DQSEX,\n1,M,\n"), spec)
    assert list(df.columns) == ["id", "DQSEX"]


def test_unsupported_format(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    with pytest.raises(ReadError, match="unsupported file format"):
        read_responses(write_csv(tmp_path, "id\n1\n"), "ods", spec)


def test_dispatcher_uses_the_format_not_the_suffix(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_csv(tmp_path, "id,DQAGE\n1,15\n")
    assert read_responses(path, "csv", spec)["DQAGE"].tolist() == [15]
    with pytest.raises(ReadError, match="XLSX"):
        read_responses(path, "xlsx", spec)


# --- XLSX ----------------------------------------------------------------------------


def test_xlsx_types_and_values(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_xlsx(
        tmp_path,
        [
            HEADER.split(","),
            [10, "2025-08-22", "W", 15, 2, "Y", None],
            [11, "2025-08-22", "M", 16, 0, None, None],
        ],
    )
    df = read_xlsx_responses(path, spec)
    assert df["id"].dtype == pd.Int64Dtype()
    assert df["DQAGE"].tolist() == [15, 16]
    assert df["DQSEX"].dtype == STRING
    assert df["DIAGQ1[DEPR]"].isna().tolist() == [False, True]
    assert df["DIAGQ1[other]"].isna().all()


def test_xlsx_strips_and_blanks(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_xlsx(
        tmp_path,
        [[" id ", " DQSEX ", "DQAGE"], [1, "  W ", 15], [2, "   ", None], [None] * 3],
    )
    df = read_xlsx_responses(path, spec)
    assert list(df.columns) == ["id", "DQSEX", "DQAGE"]
    assert df["DQSEX"].isna().tolist() == [False, True]
    assert df["id"].tolist() == [1, 2]


def test_xlsx_numbers_and_dates_become_csv_text(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_xlsx(
        tmp_path,
        [
            ["id", "submitdate", "startdate", "DQAGE", "PHQ9[PHQQ1]", "DQSEX"],
            [1, datetime(2025, 8, 22, 9, 5, 7), datetime(2025, 8, 21), 15.0, 2.5, 3.0],
        ],
    )
    df = read_xlsx_responses(path, spec)
    assert df["submitdate"].tolist() == ["2025-08-22 09:05:07"]
    assert df["startdate"].tolist() == ["2025-08-21 00:00:00"]
    assert df["DQAGE"].tolist() == [15]
    assert df["DQAGE"].dtype == pd.Int64Dtype()
    assert df["PHQ9[PHQQ1]"].dtype == STRING
    assert df["PHQ9[PHQQ1]"].tolist() == ["2.5"]
    assert df["DQSEX"].tolist() == ["3"]


def test_xlsx_stray_empty_columns_are_dropped(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    path = write_xlsx(tmp_path, [["id", "DQSEX", None], [1, "M", None]])
    assert list(read_xlsx_responses(path, spec).columns) == ["id", "DQSEX"]


def test_xlsx_duplicate_headings(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = write_xlsx(tmp_path, [["id", "id"], [1, 2]])
    with pytest.raises(ReadError, match="duplicate headings"):
        read_xlsx_responses(path, spec)


def test_xlsx_not_a_workbook(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = tmp_path / "responses.xlsx"
    path.write_text("id,DQSEX\n1,SECRETVALUE\n", encoding="utf-8")
    with pytest.raises(ReadError, match="not a readable XLSX") as info:
        read_xlsx_responses(path, spec)
    assert "SECRETVALUE" not in str(info.value)


def test_xlsx_empty_sheet(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    path = tmp_path / "responses.xlsx"
    openpyxl.Workbook().save(path)
    with pytest.raises(ReadError, match="empty"):
        read_xlsx_responses(path, spec)


def test_xlsx_missing_file(tmp_path: Path, spec: QuestionnaireSpec) -> None:
    with pytest.raises(ReadError, match="file not found"):
        read_xlsx_responses(tmp_path / "nothing.xlsx", spec)


# --- same data, both formats ---------------------------------------------------------


def test_same_hand_made_dataset_gives_equal_frames(
    tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    csv_path = write_csv(
        tmp_path,
        "id,submitdate,startdate,DQSEX,DQAGE,PHQ9[PHQQ1],DIAGQ1[DEPR],DIAGQ1[other]\n"
        "1,2025-08-22,,W,15,2,Y,\n"
        "2,2025-08-22,,M,16,x,,hello\n"
        "3,2025-08-22,,,,0,,\n",
    )
    xlsx_path = write_xlsx(
        tmp_path,
        [
            [
                "id",
                "submitdate",
                "startdate",
                "DQSEX",
                "DQAGE",
                "PHQ9[PHQQ1]",
                "DIAGQ1[DEPR]",
                "DIAGQ1[other]",
            ],
            [1, "2025-08-22", None, "W", 15, 2, "Y", None],
            [2, "2025-08-22", None, "M", 16, "x", None, "hello"],
            [3, "2025-08-22", None, None, None, 0, None, None],
        ],
    )
    pd.testing.assert_frame_equal(
        read_responses(csv_path, "csv", spec), read_responses(xlsx_path, "xlsx", spec)
    )


# --- bundle --------------------------------------------------------------------------


def write_bundle(directory: Path, *, file: str = "responses.csv") -> None:
    manifest = {
        "schema_version": 1,
        "school": {"id": "demo", "name": "Demo School"},
        "wave": {"label": "2026", "fieldwork_end": "2026-05-15"},
        "survey": {"questionnaire_version": "2026.1"},
        "responses": {"file": file, "format": "csv"},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_load_bundle(tmp_path: Path) -> None:
    write_bundle(tmp_path)
    (tmp_path / "responses.csv").write_text("id,DQAGE\n1,15\n", encoding="utf-8")
    dataset = load_bundle(tmp_path)
    assert dataset.manifest.school.id == "demo"
    assert dataset.responses["DQAGE"].tolist() == [15]


def test_load_bundle_missing_responses(tmp_path: Path) -> None:
    write_bundle(tmp_path)
    with pytest.raises(ReadError, match=r"responses\.csv: file not found"):
        load_bundle(tmp_path)


def test_load_bundle_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match=r"manifest\.json"):
        load_bundle(tmp_path)
