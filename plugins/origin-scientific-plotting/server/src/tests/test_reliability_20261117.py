import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from origin_pro_mcp.labtalk_safe import positive_column, positive_int
from origin_pro_mcp import origin_connection
from origin_pro_mcp import daemon, existing_origin
from origin_pro_mcp.tools import fitting, graph, worksheet, style_helpers

class ReliabilityTests(unittest.TestCase):
    def test_unbound_connection_never_launches_or_attaches(self):
        origin_connection.clear_session_origin()
        with patch('win32com.client.Dispatch') as dispatch, \
             patch('win32com.client.DispatchEx') as dispatch_ex:
            with self.assertRaisesRegex(RuntimeError, 'Refusing implicit'):
                origin_connection.get_origin()
        dispatch.assert_not_called()
        dispatch_ex.assert_not_called()

    def test_legacy_automatic_cleanup_switches_cannot_enable_closing(self):
        with patch.dict('os.environ', {'ORIGIN_PRO_MCP_SWEEP_ORPHANS': '1',
                                       'ORIGIN_PRO_MCP_REAP_CLOSE': '1'}):
            self.assertFalse(daemon._sweep_orphans_enabled())
            self.assertFalse(daemon._reap_close_enabled())

    def test_timeout_retains_pending_ticket_and_session(self):
        d = daemon.Daemon()
        d._dispatch_timeout = 1
        d._pool = unittest.mock.Mock()
        conn = object()
        ticket = {'answered': False, 'done': False, 'conn': conn,
                  'request_id': 'request', 'timeout': 1}
        d._dispatch_tickets['session'] = ticket
        with patch.object(d, '_dialog_note', return_value=None), \
             patch.object(d, '_safe_send') as send:
            d._on_dispatch_timeout('session', None)
        self.assertIs(d._dispatch_tickets['session'], ticket)
        self.assertFalse(ticket['done'])
        self.assertTrue(ticket['answered'])
        d._pool.discard.assert_not_called()
        self.assertIn('result is unknown', send.call_args.args[1]['error'])

    def test_created_graph_tracking_is_cleared_with_the_session(self):
        origin_connection.set_session_origin(object())
        self.addCleanup(origin_connection.clear_session_origin)
        origin_connection.remember_created_graph('Graph1')
        self.assertTrue(origin_connection.is_session_created_graph('Graph1'))
        origin_connection.clear_session_origin()
        self.assertFalse(origin_connection.is_session_created_graph('Graph1'))

    def test_isolated_factory_refuses_an_existing_com_peer(self):
        app = unittest.mock.Mock()
        with patch('win32com.client.DispatchEx', return_value=app) as dispatch, \
             patch.object(daemon, '_origin_process_pids', side_effect=[{77}, {77,88}]), \
             patch.object(existing_origin, 'query_peer_pid', return_value=77):
            with self.assertRaisesRegex(RuntimeError, 'new verified server'):
                daemon._real_origin_factory()
        dispatch.assert_called_once_with('Origin.Application')
        app.Exit.assert_not_called()
        app.Close.assert_not_called()

    def test_isolated_factory_uses_the_server_pid_instead_of_smallest_new_pid(self):
        app = unittest.mock.Mock()
        with patch('win32com.client.DispatchEx', return_value=app), \
             patch.object(daemon, '_origin_process_pids', side_effect=[{77}, {77,88,99}, {77,88,99}]), \
             patch.object(existing_origin, 'query_peer_pid', return_value=99), \
             patch.object(existing_origin, '_process_identity', return_value={
                 'pid':99, 'image':'C:/Origin/Origin64.exe','creation_filetime':123}), \
             patch.object(daemon, 'record_spawned_pid') as record:
            self.assertIs(daemon._real_origin_factory(), app)
            self.assertEqual(daemon._real_origin_get_pid(app), 99)
        record.assert_called_once_with(99)

    def test_indices_are_positive_integers(self):
        for f in (positive_column, positive_int):
            for v in (True, 0, -1, 1.2, math.nan):
                with self.subTest(f=f, value=v), self.assertRaises(ValueError): f(v, "index")
            self.assertEqual(f(1, "index"), 1)

    def test_fit_rejects_unverified_weight_before_origin(self):
        with patch.object(fitting, "require_worksheet", side_effect=AssertionError("COM reached")):
            with self.assertRaisesRegex(ValueError, "Weighted fitting"):
                fitting.curve_fit("Book1", "Sheet1", 1, 2, y_error_col=3)

    def test_fit_rejects_nonfinite_before_origin(self):
        with patch.object(fitting, "require_worksheet", side_effect=AssertionError("COM reached")):
            for kw in ({"x_min": math.nan}, {"x_max": math.inf}, {"function":"gauss", "peaks":2, "peak_centers":"1,nan"}):
                with self.subTest(kw=kw), self.assertRaisesRegex(ValueError, "finite"):
                    fitting.curve_fit("Book1", "Sheet1", 1, 2, **kw)

    def test_failed_import_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"data.csv"; path.write_text("x,y\n1,2\n")
            with patch("origin_pro_mcp.originpro_backend.is_available", return_value=False), patch.object(worksheet,"get_origin"), patch.object(worksheet,"graph_names",return_value=[]), patch.object(worksheet,"execute_labtalk",return_value=False) as execute:
                with self.assertRaisesRegex(ValueError,"partially executed"):
                    worksheet._import_csv_to_worksheet_impl(str(path))
                self.assertEqual(execute.call_count,1)

    def test_empty_export_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"out.png"
            def fake_execute(cmd): path.touch(); return True
            with patch("origin_pro_mcp.originpro_backend.is_available", return_value=False), patch.object(graph,"require_graph"), patch.object(graph,"activate_window"), patch.object(graph,"execute_labtalk",side_effect=fake_execute):
                with self.assertRaisesRegex(ValueError,"empty file"):
                    graph._export_via_expgraph("Graph1",str(path),width=1200)

    def test_new_plot_settle_waits_for_com_enumeration(self):
        visible = [{"name": "Book1_Y", "is_error": False}]
        with patch.object(style_helpers, "get_plot_info",
                          side_effect=[[], [], visible]) as enumerate_plots, \
             patch("time.sleep"):
            style_helpers.settle_new_plots("Graph1", 1, timeout_s=1)
        self.assertEqual(enumerate_plots.call_count, 3)

    def test_new_plot_settle_raises_on_timeout(self):
        with patch.object(style_helpers, "get_plot_info", return_value=[]), \
             patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "exposed 0"):
                style_helpers.settle_new_plots("Graph1", 1, timeout_s=0)

    def test_created_graph_reads_plot_names_with_labtalk_fallback(self):
        with patch.object(style_helpers, "acquire_graph_layer",
                          side_effect=RuntimeError("COM layer unavailable")), \
             patch.object(style_helpers, "is_session_created_graph",
                          return_value=True), \
             patch.object(style_helpers, "activate_window"), \
             patch.object(style_helpers, "execute_labtalk", return_value=True) as execute, \
             patch.object(style_helpers, "get_lt_var", return_value=2), \
             patch.object(style_helpers, "get_lt_str", return_value="(Book_A) (Book_B)"):
            self.assertEqual(style_helpers.get_plot_names("Graph1"), ["Book_A", "Book_B"])
        execute.assert_called_once_with(
            "layer -c; _opm_plot_count = count; _opm_plot_names$ = %Z;"
        )

    def test_graph_layer_execute_fallback_is_limited_to_session_created_graph(self):
        with patch.object(style_helpers, "acquire_graph_layer",
                          side_effect=RuntimeError("COM layer unavailable")), \
             patch.object(style_helpers, "is_session_created_graph",
                          return_value=True), \
             patch.object(style_helpers, "activate_window"), \
             patch.object(style_helpers, "get_lt_str", return_value="Graph1"), \
             patch.object(style_helpers, "execute_labtalk", return_value=True) as execute:
            self.assertTrue(style_helpers.graph_layer_execute("Graph1", "layer.x.from=0;"))
        execute.assert_called_once_with("layer.x.from=0;")

        with patch.object(style_helpers, "acquire_graph_layer",
                          side_effect=RuntimeError("COM layer unavailable")), \
             patch.object(style_helpers, "is_session_created_graph",
                          return_value=False), \
             patch.object(style_helpers, "execute_labtalk") as execute:
            with self.assertRaisesRegex(RuntimeError, "COM layer unavailable"):
                style_helpers.graph_layer_execute("LoadedGraph", "layer.x.from=0;")
        execute.assert_not_called()

    def test_activate_window_skips_redundant_active_page_change(self):
        with patch.object(origin_connection, "get_lt_str", return_value="Graph1"), \
             patch.object(origin_connection, "execute_labtalk") as execute:
            origin_connection.activate_window("Graph1")
        execute.assert_not_called()

if __name__ == "__main__": unittest.main()
