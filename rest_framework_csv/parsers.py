import csv
import codecs
import io

import re
import six

from django.conf import settings
from rest_framework.parsers import BaseParser
from rest_framework.exceptions import ParseError
from rest_framework_csv.orderedrows import OrderedRows


def preprocess_stream(stream, charset):
    if six.PY2:
        # csv.py doesn't do Unicode; encode temporarily:
        return (chunk.encode(charset) for chunk in stream)
    else:
        return (chunk.decode(charset) for chunk in stream)


def postprocess_row(row, charset):
    if six.PY2:
        # decode back to Unicode, cell by cell:
        return [cell.decode(charset) for cell in row]
    else:
        return row


def unicode_csv_reader(csv_data, dialect=csv.excel, charset='utf-8', **kwargs):
    csv_data = preprocess_stream(csv_data, charset)
    csv_reader = csv.reader(csv_data, dialect=dialect, **kwargs)
    for row in csv_reader:
        yield postprocess_row(row, charset)


def universal_newlines(stream):
    for intermediate_line in stream:
        # It's possible that the stream was not opened in universal
        # newline mode. If not, we may have a single "row" that has a
        # bunch of carriage return (\r) characters that should act as
        # newlines. For that case, lets call splitlines on the row. If
        # it doesn't have any newlines, it will return a list of just
        # the row itself.
        for line in intermediate_line.splitlines():
            yield line


DOTTED_STRING_RE = re.compile('([^.]+)\.(.+)')
class CSVParser(BaseParser):
    """
    Parses CSV serialized data.

    The parser assumes the first line contains the column names.
    """

    media_type = 'text/csv'

    def parse(self, stream, media_type=None, parser_context=None):
        parser_context = parser_context or {}
        delimiter = parser_context.get('delimiter', ',')

        try:
            encoding = parser_context.get('encoding', settings.DEFAULT_CHARSET)
            rows = unicode_csv_reader(universal_newlines(stream), delimiter=delimiter, charset=encoding)
            data = OrderedRows(next(rows))
            for row in rows:
                row_data = {}
                for column_header, column_data in zip(data.header, row):
                    self._add_column_data(row_data, column_header, column_data)
                data.append(row_data)
            return data
        except Exception as exc:
            raise ParseError('CSV parse error - %s' % str(exc))

    def _add_column_data(self, row_data, column_header, column_data):
        """Add column data to the appropriate key of the row_data dict.

        If column_header is just a string like "name", add the data to
        row_data['name'].

        If column_header is a nested attribute, like 'personal_information.address',
        add it to a nested dict shared with other headers sharing the same parent.
        """
        match = DOTTED_STRING_RE.match(column_header)
        if match:
            parent_field_name = match.group(1)
            rest_of_field_name = match.group(2)

            if parent_field_name in row_data:
                field_data = row_data[parent_field_name]
                if not isinstance(field_data, dict):
                    raise ParseError('Duplicate field name: ' + parent_field_name)
            else:
                field_data = {}
                row_data[parent_field_name] = field_data

            self._add_column_data(field_data, rest_of_field_name, column_data)
        else:
            if column_header in row_data:
                raise ParseError('Duplicate field name: ' + column_header)
            row_data[column_header] = column_data
