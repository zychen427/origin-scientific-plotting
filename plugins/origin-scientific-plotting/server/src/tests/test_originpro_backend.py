import unittest
from unittest.mock import patch

from origin_pro_mcp import originpro_backend as backend
from origin_pro_mcp import origin_connection
from origin_pro_mcp import existing_origin


class _Book:
    name = "SyntheticBook"

    def __init__(self):
        self.activated = False

    def activate(self):
        self.activated = True


class OriginProBackendTests(unittest.TestCase):
    def test_graph_with_error_column_expects_two_plot_objects(self):
        layer = unittest.mock.Mock()
        layer.plot_list.side_effect = [[], [object(), object()]]
        graph = unittest.mock.MagicMock(); graph.__getitem__.return_value = layer; graph.name = 'G'
        api = unittest.mock.Mock(); api.find_sheet.return_value = object(); api.new_graph.return_value = graph
        with patch.object(backend, 'get_api', return_value=api):
            self.assertEqual(backend.create_xy_graph('G', 'B', 'S', 1, 2, 'line+symbol', y_error_col=3), 'G')
        self.assertEqual(layer.add_plot.call_args.kwargs['colyerr'], 2)

    def test_append_with_error_column_expects_two_new_objects(self):
        layer = unittest.mock.Mock()
        layer.plot_list.side_effect = [[object(), object()], [object(), object(), object(), object()]]
        graph = unittest.mock.MagicMock(); graph.__getitem__.return_value = layer
        api = unittest.mock.Mock(); api.find_sheet.return_value = object(); api.find_graph.return_value = graph
        with patch.object(backend, 'get_api', return_value=api):
            backend.add_xy_plot('G', 'B', 'S', 1, 4, 'line+symbol', y_error_col=5)
        self.assertEqual(layer.add_plot.call_args.kwargs['colyerr'], 4)

    def test_session_identity_reports_exactly_verified_target(self):
        target = {"pid": 10792, "creation_filetime": 123}
        try:
            origin_connection.set_session_origin(object(), session_id="test-session",
                                                 verified_target=target)
            identity = origin_connection.get_session_identity()
            self.assertEqual(identity["origin_pid"], 10792)
            self.assertEqual(identity["verified_target"], target)
        finally:
            origin_connection.clear_session_origin()

    def test_object_backend_is_opt_in(self):
        with patch.dict("os.environ", {"ORIGIN_PRO_MCP_USE_ORIGINPRO": "0"}):
            self.assertFalse(backend.is_available())
            with self.assertRaisesRegex(RuntimeError, "disabled by default"):
                backend.get_api()

    def test_legacy_proxy_cannot_be_enabled_by_environment(self):
        with patch.dict("os.environ", {"ORIGIN_PRO_MCP_USE_ORIGINPRO": "1"}):
            self.assertFalse(backend.is_available())
            with self.assertRaisesRegex(RuntimeError, "cannot be enabled"):
                backend.get_api()

    def test_legacy_global_proxy_is_not_present(self):
        self.assertFalse(hasattr(backend, '_install_proxy'))

    def test_new_worksheet_uses_typed_book_and_verifies_sheet_lookup(self):
        book = _Book(); sheet = unittest.mock.Mock(); sheet.get_book.return_value = book
        api = unittest.mock.Mock()
        api.new_sheet.return_value = sheet
        api.find_sheet.return_value = object()
        with patch.object(backend, "get_api", return_value=api):
            result = backend.new_worksheet("SyntheticBook", "Data")
        self.assertEqual(result, ("SyntheticBook", "Data"))
        api.new_sheet.assert_called_once_with("w", "SyntheticBook")
        api.find_sheet.assert_called_once_with("w", "[SyntheticBook]Data")

    def test_new_worksheet_does_not_report_success_without_exact_sheet(self):
        book = _Book(); sheet = unittest.mock.Mock(); sheet.get_book.return_value = book
        api = unittest.mock.Mock()
        api.new_sheet.return_value = sheet
        api.find_sheet.return_value = None
        with patch.object(backend, "get_api", return_value=api):
            with self.assertRaisesRegex(RuntimeError, "could not be verified"):
                backend.new_worksheet("SyntheticBook", "Data")

    def test_csv_import_reports_dimensions_after_reading_file(self):
        sheet = unittest.mock.Mock()
        sheet.shape = (4, 2)
        # Special methods resolve on the class, so give the fake page an indexable type.
        class IndexableBook(_Book):
            def __getitem__(self, index):
                self.requested_index = index
                return sheet

        book = IndexableBook()
        api = unittest.mock.Mock()
        api.new_book.return_value = book
        api.get_lt_str.side_effect = ["SyntheticBook", "Sheet1"]
        with patch.object(backend, "get_api", return_value=api):
            result = backend.import_csv("synthetic.csv", "SyntheticBook")
        sheet.from_file.assert_called_once_with("synthetic.csv", keep_DC=False, sparks=False)
        self.assertEqual(book.requested_index, 0)
        self.assertEqual(result, {"name": "SyntheticBook", "sheet": "Sheet1",
                                  "rows": 4, "columns": 2})



if __name__ == "__main__":
    unittest.main()
